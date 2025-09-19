"""Utility to keep a headless PyBullet scene in sync with the real robot state.

This loader can ingest ROS-style XACRO/URDF that reference
 - package://Reloj_1_description/meshes/...
 - $(find Reloj_1_description)
by rewriting those URIs to absolute filesystem paths before loading
into PyBullet. It does not evaluate xacro macros; it only removes
<xacro:include .../> tags which are not needed for visualization.
"""
import io
import struct
import math
import os
import threading
import tempfile
import re
from typing import Optional

import numpy as np
import pybullet as p
import pybullet_data

try:
    import cv2  # type: ignore
except ImportError:
    cv2 = None  # type: ignore

try:
    from PIL import Image  # type: ignore
except ImportError:
    Image = None  # type: ignore


class PyBulletVisualizer:
    """Headless PyBullet visualizer that mirrors RobotStatus values.

    If the provided URDF cannot be loaded (ROS xacro/package paths, etc.),
    falls back to a simple geometric mock so the web UI still shows frames.
    """

    def __init__(self, robot_urdf: str, width: int = 640, height: int = 360) -> None:
        self.width = width
        self.height = height
        self.robot_urdf = os.path.abspath(robot_urdf) if robot_urdf else ""
        self.lock = threading.Lock()
        self._last_frame: Optional[bytes] = None
        self.mimetype: str = "image/jpeg"

        # Connect in DIRECT mode so we can render off-screen
        self.client_id = p.connect(p.DIRECT)
        if self.client_id < 0:
            raise RuntimeError("Unable to connect to PyBullet in DIRECT mode")

        p.resetSimulation(physicsClientId=self.client_id)
        p.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=self.client_id)
        p.setGravity(0, 0, -9.8, physicsClientId=self.client_id)

        self.plane_id = p.loadURDF("plane.urdf", physicsClientId=self.client_id)

        # Geometry/state placeholders
        self.robot_id: Optional[int] = None
        self.angle_joint = 0
        self.slide_joints = [1, 2, 4, 5]
        self._have_fallback = False
        self._fallback_ids: dict[str, Optional[int]] = {"base": None, "pointer": None, "slider": None}
        self._debug_urdf_path: Optional[str] = None
        self._debug_pkg_dir: Optional[str] = None

        # Try to load the URDF. If it fails (e.g., .xacro with ROS package URIs), build a simple mock.
        try:
            if self.robot_urdf and os.path.exists(self.robot_urdf):
                urdf_to_load, pkg_dir = self._resolve_urdf_paths(self.robot_urdf)
                self._debug_urdf_path = urdf_to_load
                self._debug_pkg_dir = pkg_dir
                # Help PyBullet find relative meshes as well
                if pkg_dir and os.path.isdir(pkg_dir):
                    p.setAdditionalSearchPath(pkg_dir, physicsClientId=self.client_id)
                    # Añadir explícitamente carpeta de meshes
                    meshes_dir = os.path.join(pkg_dir, "meshes")
                    if os.path.isdir(meshes_dir):
                        p.setAdditionalSearchPath(meshes_dir, physicsClientId=self.client_id)
                base_dir = os.path.dirname(urdf_to_load)
                if base_dir:
                    p.setAdditionalSearchPath(base_dir, physicsClientId=self.client_id)
                rid = p.loadURDF(
                    urdf_to_load,
                    [0, 0, 0.01],
                    useFixedBase=True,
                    physicsClientId=self.client_id,
                )
                self.robot_id = int(rid)
        except Exception as exc:
            self.last_error = f"loadURDF failed: {exc}"
            self.robot_id = None

        if self.robot_id is None:
            # Fallback: base cylinder, a slim box as the pointer (rotates), and a small box as the slider (moves on X)
            self._have_fallback = True
            base_col = p.createCollisionShape(p.GEOM_CYLINDER, radius=0.02, height=0.02, physicsClientId=self.client_id)
            base_vis = p.createVisualShape(p.GEOM_CYLINDER, radius=0.02, length=0.02, rgbaColor=[0.3, 0.3, 0.35, 1], physicsClientId=self.client_id)
            self._fallback_ids["base"] = p.createMultiBody(baseMass=0, baseCollisionShapeIndex=base_col, baseVisualShapeIndex=base_vis, basePosition=[0, 0, 0.01], physicsClientId=self.client_id)

            pointer_col = p.createCollisionShape(p.GEOM_BOX, halfExtents=[0.12, 0.003, 0.003], physicsClientId=self.client_id)
            pointer_vis = p.createVisualShape(p.GEOM_BOX, halfExtents=[0.12, 0.003, 0.003], rgbaColor=[0.2, 0.9, 0.6, 1], physicsClientId=self.client_id)
            self._fallback_ids["pointer"] = p.createMultiBody(baseMass=0, baseCollisionShapeIndex=pointer_col, baseVisualShapeIndex=pointer_vis, basePosition=[0, 0, 0.05], physicsClientId=self.client_id)

            slider_col = p.createCollisionShape(p.GEOM_BOX, halfExtents=[0.01, 0.01, 0.01], physicsClientId=self.client_id)
            slider_vis = p.createVisualShape(p.GEOM_BOX, halfExtents=[0.01, 0.01, 0.01], rgbaColor=[0.48, 0.72, 1.0, 1], physicsClientId=self.client_id)
            self._fallback_ids["slider"] = p.createMultiBody(baseMass=0, baseCollisionShapeIndex=slider_col, baseVisualShapeIndex=slider_vis, basePosition=[-0.2, 0, 0.02], physicsClientId=self.client_id)

        # Simple camera setup looking at the robot from the side
        self.camera_target = [0, 0, 0.03]
        self.camera_distance = 0.35
        self.camera_yaw = 45
        self.camera_pitch = -25
        self.camera_up = 2

    def _resolve_urdf_paths(self, path: str) -> tuple[str, Optional[str]]:
        """Return a URDF file path suitable for PyBullet and the package_dir.

        If `path` ends with .xacro, a temporary processed file is produced:
          - removes lines with '<xacro:' to avoid unknown tags
          - replaces 'package://Reloj_1_description' with absolute package dir
          - replaces '$(find Reloj_1_description)' with absolute package dir
        For plain .urdf, only replacements are applied when needed.
        """
        base_dir = os.path.dirname(path)
        # package_dir is the parent of 'urdf' directory in both known layouts
        package_dir = os.path.abspath(os.path.join(base_dir, os.pardir))
        pkg_fs = package_dir.replace("\\", "/")
        # If python-xacro is available, prefer exact processing
        try:
            import xacro  # type: ignore
            try:
                doc = xacro.process_file(path)  # type: ignore[attr-defined]
                xml_str = doc.toprettyxml() if hasattr(doc, "toprettyxml") else str(doc)
            except Exception:
                xml_str = None
            if xml_str:
                # Replace package/find tokens in the generated XML just in case
                xml_str = xml_str.replace("$(find Reloj_1_description)", pkg_fs)
                xml_str = xml_str.replace("package://Reloj_1_description/", pkg_fs+"/")
                xml_str = xml_str.replace("package://Reloj_1_description", pkg_fs)
                tmp = tempfile.NamedTemporaryFile(prefix="reloj_urdf_", suffix=".urdf", delete=False)
                tmp.write(xml_str.encode("utf-8"))
                tmp.close()
                return tmp.name, package_dir
        except Exception:
            pass

        # Fallback: light-weight text rewrite with include inlining
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                txt = f.read()
        except Exception:
            return path, package_dir

        def _resolve_path(raw: str) -> str:
            raw = raw.strip().strip('"\'')
            if raw.startswith("$(find Reloj_1_description)"):
                return raw.replace("$(find Reloj_1_description)", pkg_fs)
            if raw.startswith("package://Reloj_1_description/"):
                return raw.replace("package://Reloj_1_description", pkg_fs)
            if not os.path.isabs(raw):
                return os.path.normpath(os.path.join(base_dir, raw)).replace("\\", "/")
            return raw.replace("\\", "/")

        def _strip_robot_wrapper(content: str) -> str:
            stripped = re.sub(r"<\?xml[^>]*\?>", "", content)
            stripped = stripped.strip()
            if stripped.startswith("<robot"):
                close = stripped.find('>')
                if close != -1:
                    stripped = stripped[close+1:]
                end = stripped.rfind("</robot>")
                if end != -1:
                    stripped = stripped[:end]
            return stripped.strip()

        def _inline_includes(s: str) -> str:
            # Replace namespace and keep content
            s2 = re.sub(r"xmlns:xacro=\"[^\"]*\"", "", s)
            pattern = re.compile(r"<\s*xacro:include\s+filename=\"([^\"]+)\"\s*/\s*>")
            while True:
                m = pattern.search(s2)
                if not m:
                    break
                inc_file = _resolve_path(m.group(1))
                try:
                    with open(inc_file, "r", encoding="utf-8", errors="ignore") as inc:
                        inc_txt = inc.read()
                except Exception:
                    inc_txt = ""
                inc_txt = _inline_includes(inc_txt)  # recursive
                inc_txt = _strip_robot_wrapper(inc_txt)
                s2 = s2[:m.start()] + inc_txt + s2[m.end():]
            s2 = s2.replace("xacro:", "")
            return s2

        txt2 = _inline_includes(txt)
        # Replace package URIs
        txt2 = txt2.replace("$(find Reloj_1_description)", pkg_fs)
        txt2 = txt2.replace("package://Reloj_1_description/", pkg_fs+"/")
        txt2 = txt2.replace("package://Reloj_1_description", pkg_fs)

        # Clean duplicated XML headers and nested robot tags
        txt2 = re.sub(r"<\?xml[^>]*\?>", "", txt2)
        match = re.search(r"<robot\b[^>]*>", txt2)
        if match:
            body = txt2[match.end():]
            body = re.sub(r"<robot\b[^>]*>", "", body)
            body = re.sub(r"</robot>", "", body)
            txt2 = txt2[:match.end()] + body + "</robot>"

        # If nothing changed and it's not xacro, reuse original path
        if (txt2 == txt) and not path.lower().endswith(".xacro"):
            return path, package_dir

        # Write a temp file
        tmp = tempfile.NamedTemporaryFile(prefix="reloj_urdf_", suffix=".urdf", delete=False)
        tmp_path = tmp.name
        try:
            tmp.write(txt2.encode("utf-8"))
        finally:
            tmp.close()
        return tmp_path, package_dir

    def shutdown(self) -> None:
        with self.lock:
            if self.client_id >= 0:
                try:
                    p.disconnect(self.client_id)
                finally:
                    self.client_id = -1

    def _mm_to_joint(self, x_mm: float) -> float:
        # Reuse the mapping used by the manual slider in pybullet_clock_sim.py
        return float(max(-0.2, min(0.0, -(x_mm / 1000.0) * 0.2)))

    def update_from_status(self, status) -> None:
        # Respect 0..355 deg range for the virtual angle
        a_deg = float(getattr(status, "a_deg", 0.0) or 0.0)
        if a_deg < 0.0:
            a_deg = 0.0
        elif a_deg > 355.0:
            a_deg = 355.0
        angle_rad = math.radians(a_deg)
        slide_pos = self._mm_to_joint(getattr(status, "x_mm", 0.0) or 0.0)

        with self.lock:
            if self.robot_id is not None:
                p.resetJointState(self.robot_id, self.angle_joint, angle_rad, physicsClientId=self.client_id)
                for idx in self.slide_joints:
                    p.resetJointState(self.robot_id, idx, slide_pos, physicsClientId=self.client_id)
            elif self._have_fallback:
                # Rotate pointer around Z at origin
                quat = p.getQuaternionFromEuler([0, 0, angle_rad])
                if self._fallback_ids["pointer"] is not None:
                    p.resetBasePositionAndOrientation(self._fallback_ids["pointer"], [0, 0, 0.05], quat, physicsClientId=self.client_id)
                # Move slider along X (map slide_pos from [-0.2..0] to [0..0.4])
                x = -slide_pos  # slide_pos is negative in [-0.2..0]
                x_mm = max(0.0, min(0.2, x))
                xpos = -0.2 + (x_mm / 0.2) * 0.4
                if self._fallback_ids["slider"] is not None:
                    p.resetBasePositionAndOrientation(self._fallback_ids["slider"], [xpos, 0, 0.02], [0, 0, 0, 1], physicsClientId=self.client_id)
            p.stepSimulation(physicsClientId=self.client_id)

            # Update extra markers for volume and flow
            try:
                vol_ml = float(getattr(status, "volumen_ml", 0.0) or 0.0)
                flow = float(getattr(status, "caudal_est_mls", getattr(status, "flow_est", 0.0)) or 0.0)
                if hasattr(status, "caudalBombaMLs") and status.caudalBombaMLs:
                    self._flow_max_ml_s = max(1.0, float(status.caudalBombaMLs))
                if self._vol_marker is not None:
                    z = 0.02 + max(0.0, min(0.25, vol_ml * self._vol_ml_to_m))
                    p.resetBasePositionAndOrientation(self._vol_marker, [0.22, 0, z], [0, 0, 0, 1], physicsClientId=self.client_id)
                if self._flow_marker is not None:
                    f = max(0.0, min(1.0, abs(flow) / max(1e-6, self._flow_max_ml_s)))
                    rgba = [0.1 + 0.9 * f, 1.0 - 0.8 * (1.0 - f), 0.1, 0.9]
                    p.changeVisualShape(self._flow_marker, -1, rgbaColor=rgba, physicsClientId=self.client_id)
            except Exception:
                pass

    def _encode_bmp(self, rgb_img) -> bytes:
        """Encode an RGB numpy array into a 24-bit BMP byte stream (no deps)."""
        h, w, _ = rgb_img.shape
        row_padded = (w * 3 + 3) & ~3
        img_size = row_padded * h
        file_size = 14 + 40 + img_size
        # BITMAPFILEHEADER
        header = struct.pack(
            '<2sIHHI', b'BM', file_size, 0, 0, 54
        )
        # BITMAPINFOHEADER
        dib = struct.pack(
            '<IIIHHIIIIII',
            40, w, h, 1, 24, 0, img_size, 2835, 2835, 0, 0
        )
        # Pixels: bottom-up, BGR
        rows = []
        pad = b"\x00" * (row_padded - w * 3)
        for y in range(h-1, -1, -1):
            row = rgb_img[y, :, :3]
            bgr = row[:, ::-1]  # RGB -> BGR
            rows.append(bgr.tobytes() + pad)
        return header + dib + b''.join(rows)

    def render_frame(self) -> Optional[bytes]:
        with self.lock:
            view = p.computeViewMatrixFromYawPitchRoll(
                cameraTargetPosition=self.camera_target,
                distance=self.camera_distance,
                yaw=self.camera_yaw,
                pitch=self.camera_pitch,
                roll=0,
                upAxisIndex=self.camera_up,
                physicsClientId=self.client_id,
            )
            proj = p.computeProjectionMatrixFOV(
                fov=60,
                aspect=float(self.width) / float(self.height),
                nearVal=0.05,
                farVal=5.0,
                physicsClientId=self.client_id,
            )
            _, _, rgb, _, _ = p.getCameraImage(
                self.width,
                self.height,
                viewMatrix=view,
                projectionMatrix=proj,
                renderer=p.ER_TINY_RENDERER,
                physicsClientId=self.client_id,
            )

        rgba = np.reshape(np.array(rgb, dtype=np.uint8), (self.height, self.width, 4))
        rgb_img = rgba[:, :, :3]
        frame: Optional[bytes] = None
        if cv2 is not None:
            bgr_img = cv2.cvtColor(rgb_img, cv2.COLOR_RGB2BGR)
            success, buf = cv2.imencode(".jpg", bgr_img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            if success:
                frame = buf.tobytes()
                self.mimetype = "image/jpeg"
        elif Image is not None:
            buf = io.BytesIO()
            Image.fromarray(rgb_img).save(buf, format="JPEG", quality=85)
            frame = buf.getvalue()
            self.mimetype = "image/jpeg"
        else:
            # Fallback: simple BMP encoder (widely supported by browsers)
            try:
                frame = self._encode_bmp(rgb_img)
                self.mimetype = "image/bmp"
            except Exception:
                frame = self._last_frame
        if frame:
            self._last_frame = frame
            return frame
        return self._last_frame
