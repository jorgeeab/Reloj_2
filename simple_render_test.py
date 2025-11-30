import time
import os
import sys
from flask import Flask, Response, render_template_string

# Importar la clase robusta del proyecto
from pybullet_visualizer import PyBulletVisualizer

# Configuración
WIDTH = 640
HEIGHT = 360
# Ruta al URDF (la misma que usa server_reloj.py)
URDF_PATH = r"c:\Users\jorge\Documents\Antigravity Proyects\Reloj_2\Robot Virtual\Robot Virtual\urdf\Reloj_1.xacro"

app = Flask(__name__)

print(f"Iniciando PyBulletVisualizer con: {URDF_PATH}")
try:
    # Usar la clase del proyecto que maneja XACRO y rutas package://
    visualizer = PyBulletVisualizer(URDF_PATH, width=WIDTH, height=HEIGHT)
    print("Robot cargado correctamente.")
except Exception as e:
    print(f"Error fatal iniciando visualizador: {e}")
    sys.exit(1)

# Configurar cámara inicial
visualizer.set_camera(target=[0, 0, 0.1], distance=0.4, yaw=45, pitch=-25)

# Hilo de animación para mover el robot
import threading
import math

def animate_robot():
    t = 0
    print("Iniciando animación del robot...")
    while True:
        # Generar movimiento senoidal
        val1 = math.sin(t) * 1.5  # +/- 1.5 radianes (~85 grados)
        val2 = math.cos(t * 0.7) * 1.0
        val3 = math.sin(t * 1.2) * 1.0
        
        # Actualizar articulaciones (nombres comunes, ajusta si tu URDF usa otros)
        joints = {
            "joint_1": val1,
            "joint_2": val2,
            "joint_3": val3,
            "joint_4": val1 * 0.5,
            "joint_5": val2 * 0.5,
            "joint_6": val3 * 0.5
        }
        
        visualizer.update_robot_state(joints)
        
        t += 0.05
        time.sleep(0.05) # 20 Hz de actualización física

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
        # Renderizar usando la clase optimizada
        frame = visualizer.render_frame()
        
        if frame:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
        
        # Intentar mantener 25 FPS (40ms)
        time.sleep(0.04)

@app.route('/stream')
def stream():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5050, threaded=True)
