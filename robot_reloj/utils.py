#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Utilidades del Sistema Robot Reloj - Versión Compatible
======================================================

Funciones y clases auxiliares para el sistema robot reloj.
Compatible con archivos existentes.
"""

import json
import time
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union, Callable
from pathlib import Path
import hashlib

# =============================================================================
# UTILIDADES DE TIEMPO
# =============================================================================

def get_timestamp() -> float:
    """Obtiene timestamp actual en segundos"""
    return time.time()

def get_datetime() -> datetime:
    """Obtiene fecha y hora actual"""
    return datetime.now()

def format_datetime(dt: datetime, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Formatea datetime a string"""
    return dt.strftime(format_str)

def parse_datetime(date_str: str, format_str: str = "%Y-%m-%d %H:%M:%S") -> datetime:
    """Parsea string a datetime"""
    return datetime.strptime(date_str, format_str)

def is_same_minute(dt1: datetime, dt2: datetime) -> bool:
    """Verifica si dos datetimes son del mismo minuto"""
    return dt1.replace(second=0, microsecond=0) == dt2.replace(second=0, microsecond=0)

def add_time(dt: datetime, **kwargs) -> datetime:
    """Añade tiempo a un datetime"""
    return dt + timedelta(**kwargs)

def time_difference(dt1: datetime, dt2: datetime) -> timedelta:
    """Calcula diferencia entre dos datetimes"""
    return abs(dt1 - dt2)

# =============================================================================
# UTILIDADES DE VALIDACIÓN
# =============================================================================

def validate_port_name(name: str) -> bool:
    """Valida nombre de puerto serial"""
    import re
    pattern = re.compile(r"^COM\d+$|^/dev/tty[A-Z0-9]+$")
    return bool(pattern.match(name))

def validate_baudrate(baudrate: int) -> bool:
    """Valida velocidad de baudios"""
    valid_rates = [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600]
    return baudrate in valid_rates

def validate_coordinates(x: float, y: float, z: float = None) -> bool:
    """Valida coordenadas del robot"""
    if not (-1000 <= x <= 1000):
        return False
    if not (-1000 <= y <= 1000):
        return False
    if z is not None and not (-1000 <= z <= 1000):
        return False
    return True

def validate_volume(volume: float) -> bool:
    """Valida volumen en ml"""
    return 0.0 <= volume <= 10000.0

def validate_energy(energy: int) -> bool:
    """Valida energía de motor (-255 a 255)"""
    return -255 <= energy <= 255

# =============================================================================
# UTILIDADES DE ARCHIVOS
# =============================================================================

def ensure_directory(path: Union[str, Path]) -> Path:
    """Asegura que un directorio existe"""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path

def safe_write_json(data: Any, file_path: Union[str, Path], **kwargs) -> bool:
    """Escribe JSON de forma segura (backup automático)"""
    try:
        file_path = Path(file_path)
        ensure_directory(file_path.parent)
        
        # Crear backup si el archivo existe
        if file_path.exists():
            backup_path = file_path.with_suffix(f".backup.{int(time.time())}")
            file_path.rename(backup_path)
        
        # Escribir nuevo archivo
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2, **kwargs)
        
        return True
    except Exception:
        # Restaurar backup si falla
        if 'backup_path' in locals() and backup_path.exists():
            try:
                backup_path.rename(file_path)
            except Exception:
                pass
        return False

def safe_read_json(file_path: Union[str, Path], default: Any = None) -> Any:
    """Lee JSON de forma segura con valor por defecto"""
    try:
        file_path = Path(file_path)
        if not file_path.exists():
            return default
        
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default

def get_file_hash(file_path: Union[str, Path]) -> str:
    """Calcula hash SHA256 de un archivo"""
    try:
        file_path = Path(file_path)
        if not file_path.exists():
            return ""
        
        hash_sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_sha256.update(chunk)
        
        return hash_sha256.hexdigest()
    except Exception:
        return ""

# =============================================================================
# UTILIDADES DE SEGURIDAD
# =============================================================================

def sanitize_filename(filename: str) -> str:
    """Sanitiza nombre de archivo para evitar inyección"""
    import re
    # Remover caracteres peligrosos
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # Limitar longitud
    if len(sanitized) > 255:
        sanitized = sanitized[:255]
    return sanitized

def validate_protocol_name(name: str) -> bool:
    """Valida nombre de protocolo"""
    import re
    pattern = re.compile(r"^[A-Za-z0-9_]+$")
    return bool(pattern.match(name)) and len(name) <= 100

def create_safe_context() -> Dict[str, Any]:
    """Crea contexto seguro para ejecución de protocolos"""
    import math
    return {
        "__builtins__": {
            "abs": abs, "min": min, "max": max, "round": round,
            "sum": sum, "len": len, "range": range, "enumerate": enumerate,
            "zip": zip, "float": float, "int": int, "str": str, "bool": bool
        },
        "math": math,
        "time": time,
        "datetime": datetime,
        "timedelta": timedelta
    }

# =============================================================================
# UTILIDADES DE THREADING
# =============================================================================

class ThreadSafeDict:
    """Diccionario thread-safe"""
    
    def __init__(self):
        self._data = {}
        self._lock = threading.RLock()
    
    def __getitem__(self, key):
        with self._lock:
            return self._data[key]
    
    def __setitem__(self, key, value):
        with self._lock:
            self._data[key] = value
    
    def __delitem__(self, key):
        with self._lock:
            del self._data[key]
    
    def __contains__(self, key):
        with self._lock:
            return key in self._data
    
    def get(self, key, default=None):
        with self._lock:
            return self._data.get(key, default)
    
    def setdefault(self, key, default=None):
        with self._lock:
            return self._data.setdefault(key, default)
    
    def update(self, other):
        with self._lock:
            self._data.update(other)
    
    def clear(self):
        with self._lock:
            self._data.clear()
    
    def copy(self):
        with self._lock:
            return dict(self._data)
    
    def keys(self):
        with self._lock:
            return list(self._data.keys())
    
    def values(self):
        with self._lock:
            return list(self._data.values())
    
    def items(self):
        with self._lock:
            return list(self._data.items())

class RateLimiter:
    """Limitador de tasa de requests"""
    
    def __init__(self, max_requests: int, time_window: float):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = []
        self._lock = threading.Lock()
    
    def allow_request(self) -> bool:
        """Verifica si se permite un request"""
        now = time.time()
        
        with self._lock:
            # Limpiar requests antiguos
            self.requests = [req_time for req_time in self.requests 
                           if now - req_time < self.time_window]
            
            # Verificar límite
            if len(self.requests) >= self.max_requests:
                return False
            
            # Añadir request actual
            self.requests.append(now)
            return True
    
    def get_remaining_requests(self) -> int:
        """Obtiene requests restantes"""
        now = time.time()
        
        with self._lock:
            self.requests = [req_time for req_time in self.requests 
                           if now - req_time < self.time_window]
            return max(0, self.max_requests - len(self.requests))

# =============================================================================
# UTILIDADES DE CONVERSIÓN
# =============================================================================

def normalize_angle(angle: float) -> float:
    """Normaliza ángulo a rango 0-360"""
    while angle < 0:
        angle += 360
    while angle >= 360:
        angle -= 360
    return angle

def degrees_to_radians(degrees: float) -> float:
    """Convierte grados a radianes"""
    import math
    return degrees * math.pi / 180.0

def radians_to_degrees(radians: float) -> float:
    """Convierte radianes a grados"""
    import math
    return radians * 180.0 / math.pi

def mm_to_steps(mm: float, steps_per_mm: float) -> int:
    """Convierte milímetros a pasos de motor"""
    return int(mm * steps_per_mm)

def steps_to_mm(steps: int, steps_per_mm: float) -> float:
    """Convierte pasos de motor a milímetros"""
    return steps / steps_per_mm

def ml_to_flow_rate(volume_ml: float, time_seconds: float) -> float:
    """Calcula caudal en ml/s"""
    if time_seconds <= 0:
        return 0.0
    return volume_ml / time_seconds

# =============================================================================
# UTILIDADES DE LOGGING
# =============================================================================

class ColoredLogger:
    """Logger con colores para consola"""
    
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
        'RESET': '\033[0m'      # Reset
    }
    
    @classmethod
    def log(cls, message: str, level: str = "INFO", use_colors: bool = True):
        """Registra mensaje con color"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        if use_colors and level in cls.COLORS:
            color = cls.COLORS[level]
            reset = cls.COLORS['RESET']
            print(f"{color}[{timestamp}] [{level}] {message}{reset}", flush=True)
        else:
            print(f"[{timestamp}] [{level}] {message}", flush=True)

# =============================================================================
# FUNCIONES DE CONVENIENCIA
# =============================================================================

def retry_operation(operation: Callable, max_retries: int = 3, 
                   delay: float = 1.0, backoff_factor: float = 2.0):
    """Ejecuta operación con reintentos automáticos"""
    last_exception = None
    
    for attempt in range(max_retries + 1):
        try:
            return operation()
        except Exception as e:
            last_exception = e
            if attempt < max_retries:
                time.sleep(delay * (backoff_factor ** attempt))
    
    raise last_exception

def timeout_operation(operation: Callable, timeout_seconds: float):
    """Ejecuta operación con timeout"""
    import concurrent.futures
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(operation)
        try:
            return future.result(timeout=timeout_seconds)
        except concurrent.futures.TimeoutError:
            raise TimeoutError(f"Operación excedió timeout de {timeout_seconds} segundos")

def create_unique_id(prefix: str = "") -> str:
    """Crea ID único basado en timestamp y random"""
    import random
    timestamp = int(time.time() * 1000)
    random_part = random.randint(1000, 9999)
    return f"{prefix}{timestamp}_{random_part}"

if __name__ == "__main__":
    # Ejemplos de uso
    print("=== Utilidades del Sistema Robot Reloj (Compatibles) ===")
    
    # Tiempo
    print(f"Timestamp: {get_timestamp()}")
    print(f"DateTime: {get_datetime()}")
    
    # Validación
    print(f"Puerto válido COM6: {validate_port_name('COM6')}")
    print(f"Baudrate válido 115200: {validate_baudrate(115200)}")
    
    # Conversión
    print(f"Ángulo normalizado 450°: {normalize_angle(450)}")
    print(f"90° a radianes: {degrees_to_radians(90):.4f}")
    
    # Logger
    ColoredLogger.log("Mensaje informativo", "INFO")
    ColoredLogger.log("Advertencia", "WARNING")
    ColoredLogger.log("Error crítico", "ERROR")
