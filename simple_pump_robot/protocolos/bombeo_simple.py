import time
import gymnasium as gym
from gymnasium import spaces
import numpy as np

class BombeoSimple(gym.Env):
    """
    Protocolo de bombeo simple para robot estático (solo bomba).
    
    Este protocolo activa la bomba para entregar un volumen específico
    o durante un tiempo determinado. No realiza movimientos.
    """
    
    # Esquema de parámetros para generación automática de UI
    PARAMETERS = {
        "volume_ml": {
            "type": "number",
            "label": "Volumen (ml)",
            "default": 100.0,
            "min": 0,
            "max": 5000,
            "step": 10,
            "required": False,
            "description": "Volumen objetivo a bombear (opcional si se define duración)"
        },
        "duration_s": {
            "type": "number",
            "label": "Duración (s)",
            "default": 0,
            "min": 0,
            "max": 3600,
            "step": 1,
            "required": False,
            "description": "Tiempo de bombeo en segundos (si es 0, usa volumen)"
        },
        "speed": {
            "type": "number",
            "label": "Velocidad Bomba (0-255)",
            "default": 255,
            "min": 0,
            "max": 255,
            "step": 1,
            "required": True,
            "description": "Potencia de la bomba (PWM)"
        }
    }

    def __init__(self, env_config=None):
        self.env = env_config.get("robot_env")
        if self.env is None:
            raise ValueError("Se requiere 'robot_env' en env_config")
            
        # Parámetros
        self.volume_ml = float(env_config.get("volume_ml", 100.0))
        self.duration_s = float(env_config.get("duration_s", 0.0))
        self.speed = int(env_config.get("speed", 255))
        
        # Estado interno
        self.start_time = None
        self.initial_volume = 0.0
        self.target_volume = 0.0
        
        # Espacios de observación y acción (Gym standard)
        # Obs: [volumen_acumulado, tiempo_transcurrido]
        self.observation_space = spaces.Box(low=0, high=np.inf, shape=(2,), dtype=np.float32)
        # Action: [potencia_bomba] (0-1 float mapeado a 0-255)
        self.action_space = spaces.Box(low=0, high=1, shape=(1,), dtype=np.float32)

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        
        # Inicializar estado
        self.start_time = time.time()
        self.initial_volume = 0.0
        if hasattr(self.env, "get_volumen_acumulado_ml"):
             self.initial_volume = self.env.get_volumen_acumulado_ml()
        
        # Calcular objetivo
        if self.duration_s > 0:
            # Si es por tiempo, el volumen objetivo es secundario (o estimado)
            self.target_volume = float('inf') 
        else:
            # Si es por volumen
            self.target_volume = self.initial_volume + self.volume_ml
            
        # Iniciar bomba
        self.env.set_energia_bomba(self.speed)
        
        return self._get_obs(), {}

    def step(self, action):
        # En este protocolo simple, la acción externa se ignora mayormente
        # ya que es un proceso determinista, pero permitimos modulación si se desea.
        
        # Actualizar entorno
        self.env.step()
        
        # Obtener estado actual
        current_vol = 0.0
        if hasattr(self.env, "get_volumen_acumulado_ml"):
            current_vol = self.env.get_volumen_acumulado_ml()
            
        elapsed_time = time.time() - self.start_time
        
        # Verificar condiciones de término
        terminated = False
        truncated = False
        
        if self.duration_s > 0:
            # Modo tiempo
            if elapsed_time >= self.duration_s:
                terminated = True
        else:
            # Modo volumen
            if current_vol >= self.target_volume:
                terminated = True
                
        # Calcular recompensa (progreso hacia el objetivo)
        reward = 1.0 if not terminated else 100.0
        
        # Detener bomba si terminamos
        if terminated:
            self.env.set_energia_bomba(0)
            
        return self._get_obs(), reward, terminated, truncated, {}

    def _get_obs(self):
        current_vol = 0.0
        if hasattr(self.env, "get_volumen_acumulado_ml"):
            current_vol = self.env.get_volumen_acumulado_ml()
        elapsed = time.time() - (self.start_time or time.time())
        return np.array([current_vol, elapsed], dtype=np.float32)

    def render(self):
        pass
        
    def close(self):
        if self.env:
            self.env.set_energia_bomba(0)
            # Simular comportamiento de UI: resetear volumen al finalizar
            if hasattr(self.env, "reset_volumen"):
                time.sleep(1.0)
                self.env.reset_volumen()
