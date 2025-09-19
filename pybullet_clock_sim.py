import asyncio
import math
import time
from typing import List

import numpy as np
import pybullet as p
import pybullet_data
import os

from pid_model import PID

# Initialize PyBullet in GUI mode
p.connect(p.GUI)
p.setAdditionalSearchPath(pybullet_data.getDataPath())
p.setGravity(0, 0, -9.8)

# Load plane and robot URDF
planeId = p.loadURDF("plane.urdf")
# Resolve path to the robot description relative to this file
ROBOT_XACRO = os.path.join(
    os.path.dirname(__file__),
    "Protocolo_Reloj",
    "Reloj_1_description",
    "urdf",
    "Reloj_1.xacro",
)
robotId = p.loadURDF(ROBOT_XACRO, [0, 0, 0.01], useFixedBase=True)

# Debug sliders to manually move the robot
slider_revolucion = p.addUserDebugParameter("Revolución", 0, 360, 0)
slider_corredera = p.addUserDebugParameter("Corredera", 0, 1000, 0)

revolucion_joint_index = 0
corredera_joint_indices = [1, 2, 4, 5]


def move_joints(
    robot_id: int,
    joint_indices: List[int],
    target_positions: List[float],
    max_force: float = 10.0,
) -> None:
    """Move multiple joints to the given positions."""
    for j_index, target in zip(joint_indices, target_positions):
        p.setJointMotorControl2(
            bodyIndex=robot_id,
            jointIndex=j_index,
            controlMode=p.POSITION_CONTROL,
            targetPosition=target,
            force=max_force,
        )


class WaterFlowSensor:
    def __init__(self, relationship_factor: float):
        self.relationship_factor = relationship_factor

    def read_flow_rate(self, valve_position: float) -> float:
        return valve_position * self.relationship_factor


class SimulatedDCMotor:
    def __init__(self, motor_name: str):
        self.motor_name = motor_name
        self.speed = 0.0
        self.position = 0.0

    def set_speed(self, speed: float) -> None:
        self.speed = speed

    def run(self, speed: float) -> None:
        self.position += speed

    def stop(self) -> None:
        self.speed = 0.0

    def get_position(self) -> float:
        return self.position


class PyBulletDCMotor:
    def __init__(self, robot_id: int, joint_index: int):
        self.robot_id = robot_id
        self.joint_index = joint_index

    def set_speed(self, speed: float) -> None:
        p.setJointMotorControl2(
            self.robot_id,
            self.joint_index,
            p.VELOCITY_CONTROL,
            targetVelocity=speed,
        )

    def set_position(self, position: float) -> None:
        p.setJointMotorControl2(
            self.robot_id,
            self.joint_index,
            p.POSITION_CONTROL,
            targetPosition=position,
        )

    def get_position(self) -> float:
        joint_state = p.getJointState(self.robot_id, self.joint_index)
        return joint_state[0]


class RobotController:
    def __init__(self) -> None:
        self.pid_angle = PID(1, 1, 0.2)
        self.pid_corredera = PID(1, 1, 0.2)
        self.pid_valvula = PID(15, 0, 0)
        self.water_sensor = WaterFlowSensor(relationship_factor=1.0)

        self.motor_angle = PyBulletDCMotor(robotId, revolucion_joint_index)
        self.motores_corredera = [
            PyBulletDCMotor(robotId, i) for i in corredera_joint_indices
        ]
        self.motor_valvula = SimulatedDCMotor("MotorV")

        self.servoH = SimulatedDCMotor("ServoH")
        self.servoV = SimulatedDCMotor("ServoV")

        self.last_update = 0.0
        self.update_interval = 0.3

        self.A_req = 0.0
        self.X_req = 0.0
        self.vel_req = 0.0

        self.manual = False
        self.manualA = 0
        self.manualX = 0
        self.manualV = 0

        self.serial_connection = None

    def recibir_datos(self, comando: str) -> None:
        try:
            params = comando.split(",")
            if params[0] == "reset":
                self.setup()
                return

            anguloH = int(params[0])
            anguloV = int(params[1])
            self.servoH.set_speed(anguloH)
            self.servoV.set_speed(anguloV)

            self.vel_req = float(params[2])
            self.A_req = float(params[3])
            self.X_req = float(params[4])

            self.pid_valvula.kp = float(params[5])
            self.pid_valvula.ki = float(params[6])
            self.pid_valvula.kd = float(params[7])
            self.pid_angle.kp = float(params[8])
            self.pid_angle.ki = float(params[9])
            self.pid_angle.kd = float(params[10])
            self.pid_corredera.kp = float(params[11])
            self.pid_corredera.ki = float(params[12])
            self.pid_corredera.kd = float(params[13])

            calibrar = int(params[14])
            if calibrar == 1:
                self.calibrate_compass()

            self.manual = params[15] == "1"
            if self.manual:
                self.manualA = int(params[16])
                self.manualX = int(params[17])
                self.manualV = int(params[18])
                self.controlar_motores_manual()

            if len(params) > 19:
                self.water_sensor.relationship_factor = float(params[19])
        except ValueError as e:
            print(f"Error processing command: {comando} - {e}")

    def enviar_datos(self) -> None:
        now = time.time()
        if now - self.last_update >= self.update_interval:
            self.last_update = now

            angH = self.servoH.get_position()
            angV = self.servoV.get_position()
            inputA = self.motor_angle.get_position()
            inputX = self.motores_corredera[0].get_position()
            inputV = self.water_sensor.read_flow_rate(self.motor_valvula.get_position())

            datos = (
                f"V,{angH},{angV},{inputV},{inputA},{inputX},{self.vel_req},{self.A_req},"
                f"{self.X_req},{self.pid_valvula.kp},{self.pid_valvula.ki},{self.pid_valvula.kd},"
                f"{self.pid_angle.kp},{self.pid_angle.ki},{self.pid_angle.kd},"
                f"{self.pid_corredera.kp},{self.pid_corredera.ki},{self.pid_corredera.kd},"
                f"{self.water_sensor.relationship_factor}"
            )

            print(datos)
            if self.serial_connection and self.serial_connection.ser:
                self.serial_connection.ser.write(f"{datos}\n".encode())

    def read_encoder(self, motor: SimulatedDCMotor) -> float:
        return motor.get_position()

    def calibrate_compass(self) -> None:
        print("Calibrating compass...")
        time.sleep(2)
        print("Compass calibrated.")

    def controlar_motores_manual(self) -> None:
        self.motor_angle.set_speed(self.manualA)
        for m in self.motores_corredera:
            m.set_speed(self.manualX)
        self.motor_valvula.set_speed(self.manualV)

    def actualizar_controladores(self, dt: float) -> None:
        if not self.manual:
            inputA = self.read_encoder(self.motor_angle)
            self.pid_angle.setpoint = self.A_req
            outputA = self.pid_angle.update(self.A_req, inputA, dt)
            self.motor_angle.set_speed(self.map_output(outputA))

            inputX = self.read_encoder(self.motores_corredera[0])
            self.pid_corredera.setpoint = self.X_req
            outputX = self.pid_corredera.update(self.X_req, inputX, dt)
            for m in self.motores_corredera:
                m.set_speed(self.map_output(outputX))

            inputV = self.water_sensor.read_flow_rate(self.motor_valvula.get_position())
            self.pid_valvula.setpoint = self.vel_req
            outputV = self.pid_valvula.update(self.vel_req, inputV, dt)
            self.motor_valvula.set_speed(self.map_output(outputV))

        self.enviar_datos()

    @staticmethod
    def map_output(output: float) -> float:
        if output > 0:
            return float(np.clip(output, 70, 255))
        if output < 0:
            return float(np.clip(output, -255, -70))
        return 0.0

    def setup(self) -> None:
        self.calibrate_compass()
        print("Setup complete.")

    def controlar_desde_sliders(self) -> None:
        target_angle = math.radians(p.readUserDebugParameter(slider_revolucion))
        target_corr = -(p.readUserDebugParameter(slider_corredera) / 1000.0) * 0.2
        self.motor_angle.set_position(target_angle)
        for m in self.motores_corredera:
            m.set_position(target_corr)


class SerialRobotProtocol(asyncio.Protocol):
    """Protocol that feeds commands to the controller without a real serial port."""

    def __init__(self, controller: RobotController) -> None:
        self.controller = controller
        self.controller.serial_connection = self
        self.ser = None

    def connection_made(self, transport) -> None:
        self.ser = transport
        print("Simulated serial connection ready")
        self.controller.setup()
        asyncio.create_task(self.loop())

    def data_received(self, data: bytes) -> None:
        for line in data.decode().splitlines():
            if line:
                print("Comando recibido:", line)
                self.controller.recibir_datos(line)

    async def loop(self) -> None:
        dt = 1.0 / 240.0
        while True:
            self.controller.actualizar_controladores(dt)
            self.controller.controlar_desde_sliders()
            p.stepSimulation()
            await asyncio.sleep(dt)


async def main() -> None:
    """Run the PyBullet simulation without opening a serial port."""
    controller = RobotController()
    proto = SerialRobotProtocol(controller)
    proto.connection_made(None)
    asyncio.create_task(proto.loop())
    controller.serial_connection = proto
    await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
