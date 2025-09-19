import numpy as np
import json
import queue
import threading
import time
import serial
import gym
from collections import deque
from gym import spaces


class RobotEnv(gym.Env):
    metadata = {'render.modes': ['human']}

    def __init__(self, port='COM4', baudrate=115200, controlador_port='COM13'):
        super(RobotEnv, self).__init__()

        self.action_space = gym.spaces.Box(
            low=np.array([0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, -255, -255, -255, 0, 0]),
            high=np.array([400, 180, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 1, 255, 255, 255, 1, 1]),
            dtype=np.float32
        )

        self.observation_space = gym.spaces.Box(
            low=0,
            high=400,
            shape=(23,),
            dtype=np.float32
        )

        self.port = port
        self.baudrate = baudrate
        self.ser = None
        self.data_queue = queue.Queue()
        self.current_action = np.zeros(19)
        self.memory = deque(maxlen=1000)
        self.start_time = time.time()

        self.weights = {
            'flow_rate_weight': 0.5,
            'setpoint_weight': 0.3,
            'angle_horizontal_weight': 0.1,
            'angle_vertical_weight': 0.1
        }

        self.control_mode = False
        self.reward_threshold = -10

        self.sensores = {
            'inputX': 0,
            'inputA': 0,
            'inputV': 0,
            'limite_angulo': 0,
            'limite_corredera': 0,
            'limite_valvula': 0
        }

        self.actuadores = {
            'setpoint_corredera': 0,
            'setpoint_angle': 0,
            'setpoint_water': 0,
            'pid_corredera': [0, 0, 0],
            'pid_angle': [0, 0, 0],
            'pid_valvula': [0, 0, 0],
            'manual_mode': 0,
            'energia_motor_corredera': 0,
            'energia_motor_angulo': 0,
            'energia_motor_valvula': 0,
            'calibrating': 0
        }

        self.controlador = self.Controlador(controlador_port, baudrate)

        self.controlador_data = {
            'some_controller_variable1': 0,
            'some_controller_variable2': 0
        }

        self.connect_serial()

        self.read_thread = threading.Thread(target=self.read_serial)
        self.read_thread.daemon = True
        self.read_thread.start()

        self.send_thread = threading.Thread(target=self.send_data_periodically)
        self.send_thread.daemon = True
        self.send_thread.start()

        self.control_thread = threading.Thread(target=self.control_loop)
        self.control_thread.daemon = True
        self.control_thread.start()

    def connect_serial(self):
        if self.ser is not None and self.ser.is_open:
            self.ser.close()
        try:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=1)
            time.sleep(2)
            print(f"Connected to serial port {self.port}")
            return True
        except serial.SerialException as e:
            print(f"Error connecting to serial port {self.port}: {e}")
            self.ser = None
            return False

    def disconnect_serial(self):
        if self.ser is not None and self.ser.is_open:
            self.ser.close()
            self.ser = None
            print(f"Disconnected from serial port {self.port}")

    def read_serial(self):
        time.sleep(2)
        while True:
            if self.ser is None or not self.ser.is_open:
                time.sleep(1)
                continue
            try:
                line = self.ser.readline().decode('utf-8').strip()
                if not line:
                    continue
                print(f"Received: {line}")
                parsed_data = self.parse_data(line)
                if parsed_data is not None:
                    self.data_queue.put(parsed_data)
            except serial.SerialException as e:
                print(f"Error reading serial data: {e}")
                self.ser = None
            except Exception as e:
                print(f"Unexpected error: {e}")

    def parse_data(self, line):
        try:
            data = json.loads(line)
            sensores = data.get('sensores', {})
            actuadores = data.get('actuadores', {})

            try:
                self.sensores['inputX'] = sensores.get('inputX', self.sensores['inputX'])
            except KeyError:
                print("inputX key missing in sensores")

            try:
                self.sensores['inputA'] = sensores.get('inputA', self.sensores['inputA']) % 360
            except KeyError:
                print("inputA key missing in sensores")

            try:
                self.sensores['inputV'] = sensores.get('inputV', self.sensores['inputV'])
            except KeyError:
                print("inputV key missing in sensores")

            try:
                self.sensores['limite_angulo'] = sensores.get('limite_angulo', self.sensores['limite_angulo'])
            except KeyError:
                print("limite_angulo key missing in sensores")

            try:
                self.sensores['limite_corredera'] = sensores.get('limite_corredera', self.sensores['limite_corredera'])
            except KeyError:
                print("limite_corredera key missing in sensores")

            try:
                self.sensores['limite_valvula'] = sensores.get('limite_valvula', self.sensores['limite_valvula'])
            except KeyError:
                print("limite_valvula key missing in sensores")

            try:
                self.actuadores['setpoint_corredera'] = actuadores.get('setpoint_corredera',
                                                                       self.actuadores['setpoint_corredera'])
            except KeyError:
                print("setpoint_corredera key missing in actuadores")

            try:
                self.actuadores['setpoint_angle'] = actuadores.get('setpoint_angle', self.actuadores['setpoint_angle'])
            except KeyError:
                print("setpoint_angle key missing in actuadores")

            try:
                self.actuadores['setpoint_water'] = actuadores.get('setpoint_water', self.actuadores['setpoint_water'])
            except KeyError:
                print("setpoint_water key missing in actuadores")

            try:
                self.actuadores['pid_corredera'] = actuadores.get('pid_corredera', self.actuadores['pid_corredera'])
            except KeyError:
                print("pid_corredera key missing in actuadores")

            try:
                self.actuadores['pid_angle'] = actuadores.get('pid_angle', self.actuadores['pid_angle'])
            except KeyError:
                print("pid_angle key missing in actuadores")

            try:
                self.actuadores['pid_valvula'] = actuadores.get('pid_valvula', self.actuadores['pid_valvula'])
            except KeyError:
                print("pid_valvula key missing in actuadores")

            try:
                self.actuadores['manual_mode'] = actuadores.get('manual_mode', self.actuadores['manual_mode'])
            except KeyError:
                print("manual_mode key missing in actuadores")

            try:
                self.actuadores['energia_motor_corredera'] = actuadores.get('energia_motor_corredera',
                                                                            self.actuadores['energia_motor_corredera'])
            except KeyError:
                print("energia_motor_corredera key missing in actuadores")

            try:
                self.actuadores['energia_motor_angulo'] = actuadores.get('energia_motor_angulo',
                                                                         self.actuadores['energia_motor_angulo'])
            except KeyError:
                print("energia_motor_angulo key missing in actuadores")

            try:
                self.actuadores['energia_motor_valvula'] = actuadores.get('energia_motor_valvula',
                                                                          self.actuadores['energia_motor_valvula'])
            except KeyError:
                print("energia_motor_valvula key missing in actuadores")

            try:
                self.actuadores['calibrating'] = actuadores.get('calibrating', self.actuadores['calibrating'])
            except KeyError:
                print("calibrating key missing in actuadores")

            return np.array([
                self.sensores['inputX'],
                self.sensores['inputA'],
                self.sensores['inputV'],
                self.actuadores['setpoint_corredera'],
                self.actuadores['setpoint_angle'],
                self.actuadores['setpoint_water'],
                self.actuadores['pid_corredera'][0],
                self.actuadores['pid_corredera'][1],
                self.actuadores['pid_corredera'][2],
                self.actuadores['pid_angle'][0],
                self.actuadores['pid_angle'][1],
                self.actuadores['pid_angle'][2],
                self.actuadores['pid_valvula'][0],
                self.actuadores['pid_valvula'][1],
                self.actuadores['pid_valvula'][2],
                self.actuadores['manual_mode'],
                self.actuadores['energia_motor_corredera'],
                self.actuadores['energia_motor_angulo'],
                self.actuadores['energia_motor_valvula'],
                self.actuadores['calibrating'],
                self.sensores['limite_angulo'],
                self.sensores['limite_corredera'],
                self.sensores['limite_valvula']
            ])
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON: {line} - {e}")
            return None

    def step(self, action):
        self.current_action = action
        obs = self.get_observation()
        while obs is None:
            try:
                obs = self.data_queue.get(timeout=1)
            except queue.Empty:
                continue

        reward = self.calculate_reward(obs)
        done = self.is_done(reward)

        elapsed_time = time.time() - self.start_time
        self.memory.append((elapsed_time, obs, action, reward, done))

        return obs, reward, done, {}

    def send_command(self, command):
        if self.ser is None or not self.ser.is_open:
            self.connect_serial()
        try:
            command_str = json.dumps(command) + '\n'
            print(f"Sent: {command_str}")
            if self.ser:
                self.ser.write(command_str.encode())

            self.controlador.send_response(f"Sent: {command_str}")

        except serial.SerialException as e:
            print(f"Error writing to serial port: {e}")
            self.ser = None

    def send_data_periodically(self):
        while True:
            if self.ser is not None and self.ser.is_open:
                command = {
                    'actuadores': {
                        'setpoint_corredera': float(self.current_action[0]),
                        'setpoint_angle': float(self.current_action[1]),
                        'setpoint_water': float(self.current_action[2]),
                        'pid_corredera': [float(self.current_action[3]), float(self.current_action[4]),
                                          float(self.current_action[5])],
                        'pid_angle': [float(self.current_action[6]), float(self.current_action[7]),
                                      float(self.current_action[8])],
                        'pid_valvula': [float(self.current_action[9]), float(self.current_action[10]),
                                        float(self.current_action[11])],
                        'manual_mode': int(self.current_action[12]),
                        'energia_motor_corredera': float(self.current_action[13]),
                        'energia_motor_angulo': float(self.current_action[14]),
                        'energia_motor_valvula': float(self.current_action[15]),
                        'calibrating': int(self.current_action[16])
                    }
                }
                self.send_command(command)
                print("enviando_", command)
            time.sleep(0.3)

    def calculate_reward(self, obs):

        flow_rate = obs[2]
        setpoint = obs[5]
        angle_horizontal = obs[3]
        angle_vertical = obs[4]

        reward = -(self.weights['flow_rate_weight'] * abs(flow_rate - setpoint) +
                   self.weights['setpoint_weight'] * abs(setpoint) +
                   self.weights['angle_horizontal_weight'] * abs(angle_horizontal - 90) +
                   self.weights['angle_vertical_weight'] * abs(angle_vertical - 90))

        return reward

    def is_done(self, reward):
        return reward <= self.reward_threshold

    def reset(self):
        if self.ser is None:
            self.connect_serial()
        if self.ser:
            self.ser.write(b'reset\n')
        time.sleep(2)
        self.current_action = np.zeros(19)
        self.start_time = time.time()
        return self.get_observation()

    def render(self, mode='human'):
        pass

    def get_observation(self):
        try:
            return self.data_queue.get_nowait()
        except queue.Empty:
            return None

    def get_last_steps(self, num_steps):
        return list(self.memory)[-num_steps:]

    def set_servos(self, angle_horizontal, angle_vertical, angle_valve):
        self.current_action[0] = angle_horizontal
        self.current_action[1] = angle_vertical
        self.current_action[2] = angle_valve

    def set_pid_corredera(self, kp, ki, kd):
        self.current_action[3] = kp
        self.current_action[4] = ki
        self.current_action[5] = kd

    def set_pid_angulo(self, kp, ki, kd):
        self.current_action[6] = kp
        self.current_action[7] = ki
        self.current_action[8] = kd

    def set_pid_valvula(self, kp, ki, kd):
        self.current_action[9] = kp
        self.current_action[10] = ki
        self.current_action[11] = kd

    def set_flow_setpoint(self, flow_setpoint):
        self.current_action[2] = flow_setpoint

    def set_motor_energy(self, motor, value):
        if motor == 'corredera':
            self.current_action[13] = value
        elif motor == 'angulo':
            self.current_action[14] = value
        elif motor == 'valvula':
            self.current_action[15] = value

    def set_manual_mode(self, manual):
        self.current_action[12] = 1 if manual else 0

    def calibrate_compass(self):
        self.current_action[16] = 1
        time.sleep(1)
        self.current_action[16] = 0

    def set_reward_weights(self, flow_rate_weight, setpoint_weight, angle_horizontal_weight, angle_vertical_weight):
        self.weights['flow_rate_weight'] = flow_rate_weight
        self.weights['setpoint_weight'] = setpoint_weight
        self.weights['angle_horizontal_weight'] = angle_horizontal_weight
        self.weights['angle_vertical_weight'] = angle_vertical_weight

    def control_loop(self):
        while True:
            command_str = self.controlador.receive_command()
            if command_str:
                try:
                    command = json.loads(command_str)
                    self.send_command(command)
                    self.controlador.send_response("Command executed successfully.")
                except json.JSONDecodeError:
                    self.controlador.send_response("Invalid command format.")

    class Controlador:
        def __init__(self, port='COM13', baudrate=115200):
            self.port = port
            self.baudrate = baudrate
            self.ser = None
            self.connect_serial()

        def connect_serial(self):
            if self.ser is not None and self.ser.is_open:
                self.ser.close()
            try:
                self.ser = serial.Serial(self.port, self.baudrate, timeout=1)
                time.sleep(2)
                print(f"Connected to serial port {self.port}")
                return True
            except serial.SerialException as e:
                print(f"Error connecting to serial port {self.port}: {e}")
                self.ser = None
                return False

        def disconnect_serial(self):
            if self.ser is not None and self.ser.is_open:
                self.ser.close()
                self.ser = None
                print(f"Disconnected from serial port {self.port}")

        def receive_command(self):
            while True:
                if self.ser is None or not self.ser.is_open:
                    time.sleep(1)
                    continue
                try:
                    line = self.ser.readline().decode('utf-8').strip()
                    if not line:
                        continue
                    print(f"Received command: {line}")
                    return line
                except serial.SerialException as e:
                    print(f"Error reading serial data: {e}")
                    self.ser = None
                except Exception as e:
                    print(f"Unexpected error: {e}")

        def send_response(self, response):
            if self.ser is None or not self.ser.is_open:
                self.connect_serial()
            try:
                response_str = response + '\n'
                print(f"Sent: {response_str}")
                if self.ser:
                    self.ser.write(response_str.encode())
            except serial.SerialException as e:
                print(f"Error writing to serial port: {e}")
                self.ser = None
