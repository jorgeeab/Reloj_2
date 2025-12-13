#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test Rápido - Verificación del Calendario Compartido
===================================================

Script para verificar que el calendario compartido está
correctamente inicializado y accesible desde todos los robots.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

def test_calendario():
    """Test básico del calendario compartido"""
    print("\n" + "="*60)
    print("TEST RÁPIDO - CALENDARIO COMPARTIDO")
    print("="*60)
    
    try:
        # Importar módulo
        print("\n✓ Importando módulo...")
        from reloj_core import get_shared_calendar, CalendarTask
        print("  ✅ Módulo importado correctamente")
        
        # Obtener instancia
        print("\n✓ Obteniendo instancia del calendario...")
        data_dir = PROJECT_ROOT / "data"
        calendar = get_shared_calendar(data_dir=data_dir)
        print("  ✅ Calendario inicializado")
        
        # Verificar tareas existentes
        print("\n✓ Verificando tareas existentes...")
        all_tasks = calendar.get_all_tasks()
        print(f"  ✅ Tareas actuales: {len(all_tasks)}")
        
        # Verificar estadísticas
        print("\n✓ Verificando estadísticas...")
        stats = calendar.get_statistics()
        print(f"  ✅ Total de tareas: {stats['total_tasks']}")
        print(f"  ✅ Por robot: {stats['by_robot']}")
        print(f"  ✅ Por estado: {stats['by_state']}")
        
        # Verificar vistas
        print("\n✓ Verificando vistas de calendario...")
        day_view = calendar.get_day_view()
        week_view = calendar.get_week_view()
        print(f"  ✅ Vista de hoy: {day_view['total_tasks']} tareas")
        print(f"  ✅ Vista de semana: {week_view['total_tasks']} tareas")
        
        # Verificar archivo de persistencia
        print("\n✓ Verificando persistencia...")
        calendar_file = data_dir / "shared_calendar.json"
        if calendar_file.exists():
            size = calendar_file.stat().st_size
            print(f"  ✅ Archivo encontrado ({size} bytes)")
        else:
            print("  ⚠️  Archivo no encontrado (se creará al agregar tareas)")
        
        print("\n" + "="*60)
        print("✅ TODAS LAS PRUEBAS PASARON CORRECTAMENTE")
        print("="*60)
        
        print("\n📍 Accede al calendario web en:")
        print("   · Robot Reloj: http://localhost:5000/calendar")
        print("   · Robot Pump:  http://localhost:5010/calendar")
        print("   · Robot OpUno: http://localhost:5020/calendar")
        print("\n")
        
        return True
        
    except ImportError as e:
        print(f"\n❌ ERROR: No se pudo importar el módulo")
        print(f"   Detalle: {e}")
        return False
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_calendario()
    sys.exit(0 if success else 1)
