from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any


DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATA_FILE = DATA_DIR / "hub_data.json"


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


@dataclass
class Robot:
    id: str
    name: str
    base_url: str  # e.g. http://192.168.1.45:5005
    kind: str = "hardware"  # or "virtual"
    api_key: Optional[str] = None
    created_at: str = field(default_factory=_now_iso)


@dataclass
class Plant:
    id_planta: int
    nombre: str
    fecha_plantacion: str  # ISO string
    angulo_h: float
    angulo_y: float
    longitud_slider: float
    velocidad_agua: float
    era: str


@dataclass
class Regimen:
    id_regimen: int
    planta_id: int
    era: str
    nombre: str
    descripcion: str
    frecuencia: float
    unidad_frecuencia: str  # 'dias' | 'minutos'
    fecha_inicio: str  # ISO string
    fecha_fin: Optional[str] = None
    tasks: List[Dict[str, Any]] = field(default_factory=list)  # e.g., {tarea, numero_dia, hora, tiempo_s, magnitud, unidades, detalles}


@dataclass
class Activity:
    planta_id: int
    era: str
    id_regimen: int
    fecha: str  # ISO string
    tipo_actividad: str
    detalles: str
    completada: bool = False
    magnitud: Optional[float] = None
    unidades: Optional[str] = None


@dataclass
class Store:
    robots: Dict[str, Robot] = field(default_factory=dict)
    plants: Dict[str, Plant] = field(default_factory=dict)  # key=f"{era}:{id_planta}"
    regimens: List[Regimen] = field(default_factory=list)
    activities: List[Activity] = field(default_factory=list)
    # Hub-tracked task records
    tasks: List[dict] = field(default_factory=list)

    # Volatile cache (not persisted)
    last_robot_status: Dict[str, Any] = field(default_factory=dict)

    def key_for_plant(self, era: str, id_planta: int) -> str:
        return f"{era}:{id_planta}"

    def add_robot(self, r: Robot) -> None:
        self.robots[r.id] = r

    def remove_robot(self, robot_id: str) -> bool:
        return self.robots.pop(robot_id, None) is not None

    def add_plant(self, p: Plant) -> None:
        self.plants[self.key_for_plant(p.era, p.id_planta)] = p

    def get_plant(self, era: str, id_planta: int) -> Optional[Plant]:
        return self.plants.get(self.key_for_plant(era, id_planta))

    def save(self) -> None:
        data = {
            "robots": {k: asdict(v) for k, v in self.robots.items()},
            "plants": {k: asdict(v) for k, v in self.plants.items()},
            "regimens": [asdict(r) for r in self.regimens],
            "activities": [asdict(a) for a in self.activities],
            "tasks": self.tasks,
        }
        DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls) -> "Store":
        if not DATA_FILE.exists():
            return cls()
        try:
            raw = json.loads(DATA_FILE.read_text(encoding="utf-8") or "{}")
        except Exception:
            raw = {}
        robots = {k: Robot(**v) for k, v in (raw.get("robots") or {}).items()}
        plants = {k: Plant(**v) for k, v in (raw.get("plants") or {}).items()}
        regimens = [Regimen(**v) for v in (raw.get("regimens") or [])]
        activities = [Activity(**v) for v in (raw.get("activities") or [])]
        tasks = list(raw.get("tasks") or [])
        return cls(robots=robots, plants=plants, regimens=regimens, activities=activities, tasks=tasks)
