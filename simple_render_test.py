import time
import os
import sys
import threading
import math
from flask import Flask, Response, render_template_string
import pybullet as p

# Importar la clase robusta del proyecto
from pybullet_visualizer import PyBulletVisualizer

# Configuración
WIDTH = 640
HEIGHT = 360
URDF_PATH = r"c:\Users\jorge\Documents\Antigravity Proyects\Reloj_2\Robot Virtual\Robot Virtual\urdf\Reloj_1.xacro"

app = Flask(__name__)

print(f"Iniciando PyBulletVisualizer con: {URDF_PATH}")
try:
    visualizer = PyBulletVisualizer(URDF_PATH, width=WIDTH, height=HEIGHT)
    print("Robot cargado correctamente.")
except Exception as e:
    print(f"Error fatal iniciando visualizador: {e}")
    sys.exit(1)

# Configurar cámara inicial
visualizer.set_camera(target=[0, 0, 0.1], distance=0.4, yaw=45, pitch=-25)

# Detectar joints disponibles
movable_joints = []
if visualizer.robot_id is None:
    print(f"ADVERTENCIA: No se pudo cargar el robot URDF.")
    print(f"Detalle del error: {getattr(visualizer, 'last_error', 'No disponible')}")
    print("Se usará la visualización de fallback (cubos/cilindros).")
else:
    num_joints = p.getNumJoints(visualizer.robot_id, physicsClientId=visualizer.client_id)
    print(f"Robot tiene {num_joints} articulaciones.")
    for i in range(num_joints):
        info = p.getJointInfo(visualizer.robot_id, i, physicsClientId=visualizer.client_id)
        name = info[1].decode('utf-8')
        joint_type = info[2]
        # Solo animar joints móviles (revolute=0, prismatic=1)
        if joint_type in [p.JOINT_REVOLUTE, p.JOINT_PRISMATIC]:
            print(f"Joint móvil detectado: {name} (ID: {i}, Tipo: {joint_type})")
            movable_joints.append((i, name))
        else:
            print(f"Joint estático/fijo: {name} (ID: {i})")

# Hilo de animación
def animate_robot():
    t = 0
    print("Iniciando animación del robot...")
    while True:
        if visualizer.robot_id is not None:
            for i, name in movable_joints:
                # Generar movimiento oscilatorio seguro
                val = math.sin(t + i) * 0.2
                try:
                    p.resetJointState(visualizer.robot_id, i, val, physicsClientId=visualizer.client_id)
                except Exception:
                    pass
        
        t += 0.1
        time.sleep(0.04) # 25 Hz

threading.Thread(target=animate_robot, daemon=True).start()

@app.route('/')
def index():
    return render_template_string("""
    <html>
    <head><title>Test Render Robot</title></head>
    <body style="background: #111; color: #eee; text-align: center;">
        <h1>Test de Renderizado: Robot Real</h1>
        <img id="stream" src="/stream" style="border: 2px solid #444; width: 640px; height: 360px;">
        <p id="fps">Calculando FPS...</p>
        <div style="margin-top: 20px;">
            <button onclick="fetch('/cam?yaw=45')">Yaw 45</button>
            <button onclick="fetch('/cam?yaw=135')">Yaw 135</button>
            <button onclick="fetch('/cam?yaw=225')">Yaw 225</button>
            <button onclick="fetch('/cam?yaw=315')">Yaw 315</button>
        </div>
        <script>
            let frames = 0;
            setInterval(() => {
                document.getElementById('fps').innerText = frames + " FPS (Cliente)";
                frames = 0;
            }, 1000);
            document.getElementById('stream').onload = () => frames++;
        </script>
    </body>
    </html>
    """)

@app.route('/cam')
def cam_control():
    from flask import request
    yaw = request.args.get('yaw', type=float)
    if yaw is not None:
        visualizer.set_camera(yaw=yaw)
    return "ok"

def generate_frames():
    while True:
        frame = visualizer.render_frame()
        if frame:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
        time.sleep(0.04)

@app.route('/stream')
def stream():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5050, threaded=True)
