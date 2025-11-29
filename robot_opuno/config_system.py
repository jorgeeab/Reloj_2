#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistema de Configuración Centralizada
=====================================

Sistema unificado de configuración con validación, hot-reload y perfiles.
"""

import os
import json
import yaml
from pathlib import Path
from typing import Dict, Any, Optional, Union, List
from dataclasses import dataclass, field
from enum import Enum
import threading
import time

class ConfigSource(Enum):
    """Fuentes de configuración"""
    FILE = "file"
    ENV = "env"
    DEFAULT = "default"
    RUNTIME = "runtime"

@dataclass
class ConfigValue:
    """Valor de configuración con metadatos"""
    value: Any
    source: ConfigSource
    last_updated: float
    description: str = ""
    validation_rules: Optional[Dict[str, Any]] = None

class ConfigManager:
    """Gestor de configuración centralizada"""
    
    def __init__(self, config_dir: str = "config"):
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(exist_ok=True)
        self._lock = threading.RLock()
        self._config: Dict[str, ConfigValue] = {}
        self._watchers: List[callable] = []
        self._last_reload = 0
        
        # Cargar configuración por defecto
        self._load_defaults()
        
        # Cargar desde archivos
        self._load_from_files()
        
        # Cargar desde variables de entorno
        self._load_from_env()
    
    def _load_defaults(self):
        """Carga configuración por defecto"""
        defaults = {
            # Robot
            "robot.serial_port": ConfigValue("COM3", ConfigSource.DEFAULT, time.time(), "Puerto serial del Arduino"),
            "robot.baudrate": ConfigValue(115200, ConfigSource.DEFAULT, time.time(), "Velocidad de comunicación"),
            "robot.timeout": ConfigValue(5.0, ConfigSource.DEFAULT, time.time(), "Timeout de comunicación (s)"),
            
            # Protocolos
            "protocols.default_timeout": ConfigValue(60.0, ConfigSource.DEFAULT, time.time(), "Timeout por defecto de protocolos (s)"),
            "protocols.tick_hz": ConfigValue(50.0, ConfigSource.DEFAULT, time.time(), "Frecuencia de ticks del protocolo"),
            "protocols.max_steps": ConfigValue(1000, ConfigSource.DEFAULT, time.time(), "Máximo número de pasos"),
            
            # Tareas
            "tasks.max_concurrent": ConfigValue(3, ConfigSource.DEFAULT, time.time(), "Máximo de tareas concurrentes"),
            "tasks.default_duration": ConfigValue(10.0, ConfigSource.DEFAULT, time.time(), "Duración por defecto (s)"),
            "tasks.retry_attempts": ConfigValue(3, ConfigSource.DEFAULT, time.time(), "Intentos de reintento"),
            
            # Recompensas
            "rewards.max_reward": ConfigValue(1000.0, ConfigSource.DEFAULT, time.time(), "Recompensa máxima"),
            "rewards.min_reward": ConfigValue(-100.0, ConfigSource.DEFAULT, time.time(), "Recompensa mínima"),
            "rewards.distance_weight": ConfigValue(0.4, ConfigSource.DEFAULT, time.time(), "Peso de recompensa por distancia"),
            
            # Logging
            "logging.level": ConfigValue("INFO", ConfigSource.DEFAULT, time.time(), "Nivel de logging"),
            "logging.max_file_size": ConfigValue(10485760, ConfigSource.DEFAULT, time.time(), "Tamaño máximo de archivo de log (bytes)"),
            "logging.retention_days": ConfigValue(7, ConfigSource.DEFAULT, time.time(), "Días de retención de logs"),
            
            # Servidor
            "server.host": ConfigValue("0.0.0.0", ConfigSource.DEFAULT, time.time(), "Host del servidor"),
            "server.port": ConfigValue(5001, ConfigSource.DEFAULT, time.time(), "Puerto del servidor"),
            "server.debug": ConfigValue(False, ConfigSource.DEFAULT, time.time(), "Modo debug del servidor"),
            
            # Hardware
            "hardware.motor_max_energy": ConfigValue(255, ConfigSource.DEFAULT, time.time(), "Energía máxima de motores"),
            "hardware.bomba_max_energy": ConfigValue(255, ConfigSource.DEFAULT, time.time(), "Energía máxima de bomba"),
            "hardware.position_threshold": ConfigValue(1.0, ConfigSource.DEFAULT, time.time(), "Umbral de posición (mm/grados)"),
        }
        
        with self._lock:
            self._config.update(defaults)
    
    def _load_from_files(self):
        """Carga configuración desde archivos"""
        config_files = [
            self.config_dir / "config.json",
            self.config_dir / "config.yaml",
            self.config_dir / "config.yml"
        ]
        
        for config_file in config_files:
            if config_file.exists():
                try:
                    with open(config_file, 'r', encoding='utf-8') as f:
                        if config_file.suffix in ['.yaml', '.yml']:
                            data = yaml.safe_load(f)
                        else:
                            data = json.load(f)
                    
                    self._update_config_from_dict(data, ConfigSource.FILE)
                    print(f"Configuración cargada desde: {config_file}")
                except Exception as e:
                    print(f"Error cargando configuración desde {config_file}: {e}")
    
    def _load_from_env(self):
        """Carga configuración desde variables de entorno"""
        env_mappings = {
            "ROBOT_SERIAL_PORT": "robot.serial_port",
            "ROBOT_BAUDRATE": "robot.baudrate",
            "ROBOT_TIMEOUT": "robot.timeout",
            "SERVER_HOST": "server.host",
            "SERVER_PORT": "server.port",
            "SERVER_DEBUG": "server.debug",
            "LOGGING_LEVEL": "logging.level",
        }
        
        for env_var, config_key in env_mappings.items():
            value = os.getenv(env_var)
            if value is not None:
                # Convertir tipos
                if config_key in ["robot.baudrate", "server.port", "logging.max_file_size"]:
                    value = int(value)
                elif config_key in ["robot.timeout", "protocols.default_timeout", "tasks.default_duration"]:
                    value = float(value)
                elif config_key in ["server.debug"]:
                    value = value.lower() in ['true', '1', 'yes', 'on']
                
                self.set(config_key, value, ConfigSource.ENV)
    
    def _update_config_from_dict(self, data: Dict[str, Any], source: ConfigSource):
        """Actualiza configuración desde diccionario"""
        def _flatten_dict(d, parent_key='', sep='.'):
            items = []
            for k, v in d.items():
                new_key = f"{parent_key}{sep}{k}" if parent_key else k
                if isinstance(v, dict):
                    items.extend(_flatten_dict(v, new_key, sep=sep).items())
                else:
                    items.append((new_key, v))
            return dict(items)
        
        flattened = _flatten_dict(data)
        for key, value in flattened.items():
            self.set(key, value, source)
    
    def get(self, key: str, default: Any = None) -> Any:
        """Obtiene valor de configuración"""
        with self._lock:
            if key in self._config:
                return self._config[key].value
            return default
    
    def set(self, key: str, value: Any, source: ConfigSource = ConfigSource.RUNTIME, 
            description: str = "", validation_rules: Optional[Dict[str, Any]] = None):
        """Establece valor de configuración"""
        with self._lock:
            # Validar valor si hay reglas
            if validation_rules:
                self._validate_value(key, value, validation_rules)
            
            # Crear o actualizar configuración
            self._config[key] = ConfigValue(
                value=value,
                source=source,
                last_updated=time.time(),
                description=description,
                validation_rules=validation_rules
            )
            
            # Notificar watchers
            self._notify_watchers(key, value)
    
    def _validate_value(self, key: str, value: Any, rules: Dict[str, Any]):
        """Valida valor según reglas"""
        if 'type' in rules:
            expected_type = rules['type']
            if not isinstance(value, expected_type):
                raise ValueError(f"Configuración '{key}' debe ser de tipo {expected_type}, recibido {type(value)}")
        
        if 'min' in rules and value < rules['min']:
            raise ValueError(f"Configuración '{key}' debe ser >= {rules['min']}")
        
        if 'max' in rules and value > rules['max']:
            raise ValueError(f"Configuración '{key}' debe ser <= {rules['max']}")
        
        if 'choices' in rules and value not in rules['choices']:
            raise ValueError(f"Configuración '{key}' debe ser uno de {rules['choices']}")
    
    def _notify_watchers(self, key: str, value: Any):
        """Notifica a los watchers de cambios"""
        for watcher in self._watchers:
            try:
                watcher(key, value)
            except Exception as e:
                print(f"Error en watcher de configuración: {e}")
    
    def add_watcher(self, callback: callable):
        """Añade watcher para cambios de configuración"""
        with self._lock:
            self._watchers.append(callback)
    
    def remove_watcher(self, callback: callable):
        """Remueve watcher"""
        with self._lock:
            if callback in self._watchers:
                self._watchers.remove(callback)
    
    def get_all(self) -> Dict[str, Any]:
        """Obtiene toda la configuración"""
        with self._lock:
            return {key: config.value for key, config in self._config.items()}
    
    def get_metadata(self) -> Dict[str, Dict[str, Any]]:
        """Obtiene metadatos de configuración"""
        with self._lock:
            return {
                key: {
                    'value': config.value,
                    'source': config.source.value,
                    'last_updated': config.last_updated,
                    'description': config.description
                }
                for key, config in self._config.items()
            }
    
    def save_to_file(self, filename: Optional[str] = None, format: str = "json"):
        """Guarda configuración a archivo"""
        if filename is None:
            filename = f"config.{format}"
        
        config_file = self.config_dir / filename
        
        with self._lock:
            data = self.get_all()
            
            try:
                with open(config_file, 'w', encoding='utf-8') as f:
                    if format.lower() in ['yaml', 'yml']:
                        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
                    else:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                
                print(f"Configuración guardada en: {config_file}")
            except Exception as e:
                print(f"Error guardando configuración: {e}")
    
    def reload(self):
        """Recarga configuración desde archivos"""
        current_time = time.time()
        if current_time - self._last_reload < 1.0:  # Evitar recargas muy frecuentes
            return
        
        self._last_reload = current_time
        self._load_from_files()
        self._load_from_env()
        print("Configuración recargada")

# Instancia global del gestor de configuración
config_manager = ConfigManager()

def get_config(key: str, default: Any = None) -> Any:
    """Función de conveniencia para obtener configuración"""
    return config_manager.get(key, default)

def set_config(key: str, value: Any, source: ConfigSource = ConfigSource.RUNTIME):
    """Función de conveniencia para establecer configuración"""
    config_manager.set(key, value, source)
