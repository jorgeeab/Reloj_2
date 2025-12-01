import json
import math
from datetime import datetime, timedelta
import matplotlib.pyplot as plt

# Función auxiliar para parsear fechas
def parsear_fecha(fecha_str):
    formatos = ['%Y-%m-%d %H:%M', '%Y-%m-%d']
    for formato in formatos:
        try:
            return datetime.strptime(fecha_str, formato)
        except ValueError:
            continue
    raise ValueError(f"La fecha '{fecha_str}' no coincide con los formatos esperados.")

# Clase Planta
class Planta:
    def __init__(self, id_planta, nombre, fecha_plantacion, angulo_h, angulo_y, longitud_slider, velocidad_agua, era, regimens=None):
        self.id_planta = id_planta
        self.nombre = nombre
        self.fecha_plantacion = fecha_plantacion
        self.angulo_h = angulo_h  # Ángulo en el eje H
        self.angulo_y = angulo_y  # Ángulo en el eje Y
        self.longitud_slider = longitud_slider  # Longitud del brazo
        self.velocidad_agua = velocidad_agua  # Velocidad de agua
        self.era = era  # Era a la que pertenece la planta
        self.regimens = regimens if regimens else []  # Lista de objetos Regimen

    def calcular_posicion_xy(self):
        # Convertir ángulo de grados a radianes
        angulo_rad = math.radians(self.angulo_h)
        x = self.longitud_slider * math.cos(angulo_rad)
        y = self.longitud_slider * math.sin(angulo_rad)
        return x, y

# Clase Regimen
class Regimen:
    def __init__(self, id_regimen, nombre, descripcion, frecuencia, unidad_frecuencia, fecha_inicio, fecha_fin=None):
        self.id_regimen = id_regimen
        self.nombre = nombre
        self.descripcion = descripcion
        self.frecuencia = frecuencia  # Por ejemplo, cada X unidades
        self.unidad_frecuencia = unidad_frecuencia  # 'dias' o 'minutos'
        self.fecha_inicio = fecha_inicio
        self.fecha_fin = fecha_fin
        self.actividades_programadas = []

# Clase Actividad
class Actividad:
    def __init__(self, fecha, tipo_actividad, detalles, planta_asociada):
        self.fecha = fecha
        self.tipo_actividad = tipo_actividad
        self.detalles = detalles
        self.planta_asociada = planta_asociada
        self.completada = False

# Clase PlantasManager
class PlantasManager:
    def __init__(self, archivo_datos='data/plants.json'):
        self.archivo_datos = archivo_datos
        self.plantas_por_era = {}
        self.cargar_datos()

    # Método para cargar datos desde el archivo JSON
    def cargar_datos(self):
        try:
            with open(self.archivo_datos, 'r') as file:
                data = json.load(file)
                if not isinstance(data, dict):
                    data = {}
                self.plantas_por_era = {}
                for era_name, plantas_data in data.get('plantas_por_era', {}).items():
                    plantas = []
                    for pdata in plantas_data:
                        regimens = []
                        for rdata in pdata.get('regimens', []):
                            regimen = Regimen(
                                id_regimen=rdata['id_regimen'],
                                nombre=rdata['nombre'],
                                descripcion=rdata['descripcion'],
                                frecuencia=rdata['frecuencia'],
                                unidad_frecuencia=rdata.get('unidad_frecuencia', 'dias'),
                                fecha_inicio=parsear_fecha(rdata['fecha_inicio']),
                                fecha_fin=parsear_fecha(rdata['fecha_fin']) if rdata.get('fecha_fin') else None
                            )
                            for adata in rdata.get('actividades_programadas', []):
                                actividad = Actividad(
                                    fecha=parsear_fecha(adata['fecha']),
                                    tipo_actividad=adata['tipo_actividad'],
                                    detalles=adata['detalles'],
                                    planta_asociada=None  # Se asignará después
                                )
                                actividad.completada = adata.get('completada', False)
                                regimen.actividades_programadas.append(actividad)
                            regimens.append(regimen)
                        planta = Planta(
                            id_planta=pdata['id_planta'],
                            nombre=pdata['nombre'],
                            fecha_plantacion=parsear_fecha(pdata['fecha_plantacion']),
                            angulo_h=pdata['angulo_h'],
                            angulo_y=pdata['angulo_y'],
                            longitud_slider=pdata['longitud_slider'],
                            velocidad_agua=pdata['velocidad_agua'],
                            era=era_name,
                            regimens=regimens
                        )
                        for regimen in planta.regimens:
                            for actividad in regimen.actividades_programadas:
                                actividad.planta_asociada = planta
                        plantas.append(planta)
                    self.plantas_por_era[era_name] = plantas
        except (FileNotFoundError, json.JSONDecodeError):
            self.plantas_por_era = {}

    # Método para guardar datos en el archivo JSON
    def guardar_datos(self):
        data = {'plantas_por_era': {}}
        for era_name, plantas in self.plantas_por_era.items():
            plantas_data = []
            for planta in plantas:
                pdata = {
                    'id_planta': planta.id_planta,
                    'nombre': planta.nombre,
                    'fecha_plantacion': planta.fecha_plantacion.strftime('%Y-%m-%d %H:%M'),
                    'angulo_h': planta.angulo_h,
                    'angulo_y': planta.angulo_y,
                    'longitud_slider': planta.longitud_slider,
                    'velocidad_agua': planta.velocidad_agua,
                    'regimens': []
                }
                for regimen in planta.regimens:
                    rdata = {
                        'id_regimen': regimen.id_regimen,
                        'nombre': regimen.nombre,
                        'descripcion': regimen.descripcion,
                        'frecuencia': regimen.frecuencia,
                        'unidad_frecuencia': regimen.unidad_frecuencia,
                        'fecha_inicio': regimen.fecha_inicio.strftime('%Y-%m-%d %H:%M'),
                        'fecha_fin': regimen.fecha_fin.strftime('%Y-%m-%d %H:%M') if regimen.fecha_fin else None,
                        'actividades_programadas': []
                    }
                    for actividad in regimen.actividades_programadas:
                        adata = {
                            'fecha': actividad.fecha.strftime('%Y-%m-%d %H:%M'),
                            'tipo_actividad': actividad.tipo_actividad,
                            'detalles': actividad.detalles,
                            'completada': actividad.completada
                        }
                        rdata['actividades_programadas'].append(adata)
                    pdata['regimens'].append(rdata)
                plantas_data.append(pdata)
            data['plantas_por_era'][era_name] = plantas_data
        with open(self.archivo_datos, 'w') as file:
            json.dump(data, file, indent=4)

    # Funciones para Plantas
    def agregar_planta(self, planta):
        era = planta.era
        if era not in self.plantas_por_era:
            self.plantas_por_era[era] = []
        self.plantas_por_era[era].append(planta)
        return f"Planta agregada exitosamente: {planta.nombre} (ID: {planta.id_planta}) en la era '{era}'"

    def crear_planta(self, id_planta, nombre, fecha_plantacion, angulo_h, angulo_y, longitud_slider, velocidad_agua, era):
        try:
            campos_obligatorios = ['id_planta', 'nombre', 'fecha_plantacion', 'angulo_h', 'angulo_y', 'longitud_slider', 'velocidad_agua', 'era']
            valores = {
                'id_planta': id_planta,
                'nombre': nombre,
                'fecha_plantacion': fecha_plantacion,
                'angulo_h': angulo_h,
                'angulo_y': angulo_y,
                'longitud_slider': longitud_slider,
                'velocidad_agua': velocidad_agua,
                'era': era
            }
            campos_faltantes = [campo for campo in campos_obligatorios if valores[campo] is None]

            if campos_faltantes:
                raise ValueError(f"Faltan los siguientes campos obligatorios: {', '.join(campos_faltantes)}.")

            if self.obtener_planta(id_planta, era):
                return f"Error: La planta con ID {id_planta} ya existe en la era '{era}'."

            planta = Planta(
                id_planta=id_planta,
                nombre=nombre,
                fecha_plantacion=fecha_plantacion,
                angulo_h=angulo_h,
                angulo_y=angulo_y,
                longitud_slider=longitud_slider,
                velocidad_agua=velocidad_agua,
                era=era
            )
            mensaje = self.agregar_planta(planta)
            return mensaje
        except Exception as e:
            estructura_correcta = {
                'id_planta': 'int',
                'nombre': 'str',
                'fecha_plantacion': 'datetime',
                'angulo_h': 'float',
                'angulo_y': 'float',
                'longitud_slider': 'float',
                'velocidad_agua': 'float',
                'era': 'str'
            }
            return f"Error al crear la planta: {e}. La estructura correcta es: {estructura_correcta}"

    def modificar_planta(self, id_planta, era, **kwargs):
        planta = self.obtener_planta(id_planta, era)
        if planta:
            estructura_correcta = {
                'id_planta': 'int',
                'nombre': 'str',
                'fecha_plantacion': 'datetime',
                'angulo_h': 'float',
                'angulo_y': 'float',
                'longitud_slider': 'float',
                'velocidad_agua': 'float',
                'era': 'str'
            }
            atributos_invalidos = [key for key in kwargs if not hasattr(planta, key)]
            if atributos_invalidos:
                return (f"Error: Los siguientes atributos no existen en la planta: {', '.join(atributos_invalidos)}. "
                        f"Estructura correcta de atributos para planta: {estructura_correcta}")

            for key, value in kwargs.items():
                setattr(planta, key, value)
                print(f"  - Atributo '{key}' actualizado a '{value}'")
            return f"Planta con ID {id_planta} modificada exitosamente."

        return f"No se encontró la planta con ID {id_planta} en la era '{era}'."

    def eliminar_planta(self, id_planta, era):
        if era in self.plantas_por_era:
            plantas = self.plantas_por_era[era]
            for planta in plantas:
                if planta.id_planta == id_planta:
                    plantas.remove(planta)
                    return f"Planta eliminada exitosamente: {planta.nombre} (ID: {planta.id_planta})"
        return f"Error: No se encontró la planta con ID {id_planta} en la era '{era}'."

    def obtener_planta(self, id_planta, era):
        if era in self.plantas_por_era:
            for planta in self.plantas_por_era[era]:
                if planta.id_planta == id_planta:
                    return planta
        return None

    # Funciones para Regímenes
    def crear_regimen(self, id_planta, era, id_regimen, nombre, descripcion, frecuencia, unidad_frecuencia, fecha_inicio, fecha_fin=None):
        try:
            campos_obligatorios = ['id_regimen', 'nombre', 'descripcion', 'frecuencia', 'unidad_frecuencia', 'fecha_inicio']
            valores = {
                'id_regimen': id_regimen,
                'nombre': nombre,
                'descripcion': descripcion,
                'frecuencia': frecuencia,
                'unidad_frecuencia': unidad_frecuencia,
                'fecha_inicio': fecha_inicio,
                'fecha_fin': fecha_fin
            }
            campos_faltantes = [campo for campo in campos_obligatorios if valores[campo] is None]

            if campos_faltantes:
                raise ValueError(f"Faltan los siguientes campos obligatorios: {', '.join(campos_faltantes)}.")

            planta = self.obtener_planta(id_planta, era)
            if not planta:
                return f"Error: No se encontró la planta con ID {id_planta} en la era '{era}'."

            if self.obtener_regimen(id_planta, era, id_regimen):
                return f"Error: El régimen con ID {id_regimen} ya existe para la planta {id_planta}."

            regimen = Regimen(
                id_regimen=id_regimen,
                nombre=nombre,
                descripcion=descripcion,
                frecuencia=frecuencia,
                unidad_frecuencia=unidad_frecuencia,
                fecha_inicio=fecha_inicio,
                fecha_fin=fecha_fin
            )
            planta.regimens.append(regimen)
            return f"Régimen creado exitosamente: {nombre} (ID: {id_regimen}) para la planta {id_planta}."
        except Exception as e:
            estructura_correcta = {
                'id_regimen': 'int',
                'nombre': 'str',
                'descripcion': 'str',
                'frecuencia': 'int/float',
                'unidad_frecuencia': "'dias' o 'minutos'",
                'fecha_inicio': 'datetime',
                'fecha_fin': 'datetime (opcional)'
            }
            return f"Error al crear el régimen: {e}. La estructura correcta es: {estructura_correcta}"



    def modificar_regimen(self, id_planta, era, id_regimen, **kwargs):
        regimen = self.obtener_regimen(id_planta, era, id_regimen)
        if regimen:
            estructura_correcta = {
                'id_regimen': 'int',
                'nombre': 'str',
                'descripcion': 'str',
                'frecuencia': 'int/float',
                'unidad_frecuencia': "'dias' o 'minutos'",
                'fecha_inicio': 'datetime',
                'fecha_fin': 'datetime (opcional)'
            }
            atributos_invalidos = [key for key in kwargs if not hasattr(regimen, key)]
            if atributos_invalidos:
                return (f"Error: Los siguientes atributos no existen en el régimen: {', '.join(atributos_invalidos)}. "
                        f"Estructura correcta de atributos para régimen: {estructura_correcta}")

            for key, value in kwargs.items():
                setattr(regimen, key, value)
                print(f"  - Atributo '{key}' actualizado a '{value}'")
            return f"Régimen con ID {id_regimen} modificado exitosamente."

        return f"No se encontró el régimen con ID {id_regimen} para la planta con ID {id_planta} en la era '{era}'."

    def eliminar_regimen(self, id_planta, era, id_regimen):
        planta = self.obtener_planta(id_planta, era)
        if planta:
            for regimen in planta.regimens:
                if regimen.id_regimen == id_regimen:
                    planta.regimens.remove(regimen)
                    return f"Régimen eliminado exitosamente: {regimen.nombre} (ID: {regimen.id_regimen})"
        return f"Error: No se encontró el régimen con ID {id_regimen} para la planta con ID {id_planta} en la era '{era}'."

    def obtener_regimen(self, id_planta, era, id_regimen):
        planta = self.obtener_planta(id_planta, era)
        if planta:
            for regimen in planta.regimens:
                if regimen.id_regimen == id_regimen:
                    return regimen
        return None

    # Funciones para Actividades
    def crear_actividad(self, id_planta, era, id_regimen, fecha, tipo_actividad, detalles):
        try:
            campos_obligatorios = ['fecha', 'tipo_actividad', 'detalles']
            valores = {
                'fecha': fecha,
                'tipo_actividad': tipo_actividad,
                'detalles': detalles
            }
            campos_faltantes = [campo for campo in campos_obligatorios if valores[campo] is None]

            if campos_faltantes:
                raise ValueError(f"Faltan los siguientes campos obligatorios: {', '.join(campos_faltantes)}.")

            regimen = self.obtener_regimen(id_planta, era, id_regimen)
            planta = self.obtener_planta(id_planta, era)
            if not (regimen and planta):
                return f"Error: No se pudo encontrar el régimen o la planta especificada."

            actividad = Actividad(
                fecha=fecha,
                tipo_actividad=tipo_actividad,
                detalles=detalles,
                planta_asociada=planta
            )
            regimen.actividades_programadas.append(actividad)
            return f"Actividad creada exitosamente: '{tipo_actividad}' para la planta {id_planta} en la fecha {fecha.strftime('%Y-%m-%d %H:%M')}."
        except Exception as e:
            estructura_correcta = {
                'fecha': 'datetime',
                'tipo_actividad': 'str',
                'detalles': 'str'
            }
            return f"Error al crear la actividad: {e}. La estructura correcta es: {estructura_correcta}"

    def eliminar_actividad(self, id_planta, era, id_regimen, fecha):
        regimen = self.obtener_regimen(id_planta, era, id_regimen)
        if regimen:
            for actividad in regimen.actividades_programadas:
                if actividad.fecha == fecha:
                    regimen.actividades_programadas.remove(actividad)
                    return f"Actividad eliminada exitosamente: {actividad.tipo_actividad} el {fecha.strftime('%Y-%m-%d %H:%M')}."
        return f"Error: No se encontró la actividad en la fecha {fecha.strftime('%Y-%m-%d %H:%M')}."

    def obtener_actividad(self, id_planta, era, id_regimen, fecha):
        regimen = self.obtener_regimen(id_planta, era, id_regimen)
        if regimen:
            for actividad in regimen.actividades_programadas:
                if actividad.fecha == fecha:
                    return actividad
        return None

    def marcar_actividad_completada(self, id_planta, era, id_regimen, fecha):
        actividad = self.obtener_actividad(id_planta, era, id_regimen, fecha)
        if actividad:
            actividad.completada = True
            return f"Actividad marcada como completada: {actividad.tipo_actividad} el {actividad.fecha.strftime('%Y-%m-%d')}."
        return f"Error: No se encontró la actividad en la fecha {fecha.strftime('%Y-%m-%d %H:%M')}."

    # Generar actividades basadas en los regímenes
    def generar_actividades(self):
        mensajes = []
        for era_name, plantas in self.plantas_por_era.items():
            for planta in plantas:
                for regimen in planta.regimens:
                    # Crear un conjunto de fechas y tipos de actividad ya programadas
                    actividades_programadas = set(
                        (actividad.fecha, actividad.tipo_actividad)
                        for actividad in regimen.actividades_programadas
                    )
                    fecha_actual = regimen.fecha_inicio
                    fecha_fin = regimen.fecha_fin or datetime.now() + timedelta(days=1)

                    while fecha_actual <= fecha_fin:
                        # Crear la actividad solo si no existe ya en las actividades programadas
                        if (fecha_actual, regimen.nombre) not in actividades_programadas:
                            actividad = Actividad(
                                fecha=fecha_actual,
                                tipo_actividad=regimen.nombre,
                                detalles=regimen.descripcion,
                                planta_asociada=planta
                            )
                            regimen.actividades_programadas.append(actividad)
                            mensajes.append(f"Actividad programada: {actividad.tipo_actividad} el {actividad.fecha.strftime('%Y-%m-%d %H:%M')}.")
                        # Incrementar según la frecuencia y unidad
                        if regimen.unidad_frecuencia == 'minutos':
                            fecha_actual += timedelta(minutes=regimen.frecuencia)
                        else:  # 'dias' por defecto
                            fecha_actual += timedelta(days=regimen.frecuencia)
        return mensajes if mensajes else ["No se generaron nuevas actividades."]

    # Mostrar tareas de una planta
    def mostrar_tareas_de_planta(self, id_planta, era):
        planta = self.obtener_planta(id_planta, era)
        if not planta:
            return f"Error: No se encontró la planta con ID {id_planta} en la era '{era}'."
        resultado = [f"Tareas para la planta '{planta.nombre}' (ID: {id_planta}) en la era '{era}':"]
        if not planta.regimens:
            resultado.append("No hay regímenes asignados a esta planta.")
            return resultado
        for regimen in planta.regimens:
            resultado.append(f"  Régimen '{regimen.nombre}' (ID: {regimen.id_regimen}):")
            for actividad in sorted(regimen.actividades_programadas, key=lambda x: x.fecha):
                estado = "Completada" if actividad.completada else "Pendiente"
                fecha = actividad.fecha.strftime('%Y-%m-%d %H:%M')
                resultado.append(f"    - [{estado}] {fecha}: {actividad.tipo_actividad} - {actividad.detalles}")
        return resultado

    # Método para mostrar posiciones de las plantas
    # Modificar el método para devolver una lista de posiciones en lugar de un gráfico
    def mostrar_posiciones_de_plantas(self):
        posiciones = []
        for era_name, plantas in self.plantas_por_era.items():
            for planta in plantas:
                x, y = planta.calcular_posicion_xy()
                posiciones.append({
                    'id_planta': planta.id_planta,
                    'nombre': planta.nombre,
                    'era': era_name,
                    'posicion_x': round(x, 2),
                    'posicion_y': round(y, 2)
                })
        return posiciones
if __name__ == "__main__":
    from datetime import datetime

    # Crear una instancia del gestor
    manager = PlantasManager()

    print("\n--- Intento de creación de planta con campos faltantes ---")
    mensaje = manager.crear_planta(
        id_planta=1,
        nombre='Tomate',
        fecha_plantacion=datetime(2023, 1, 1, 8, 0),
        angulo_h=30.0,
        angulo_y=None,  # Campo faltante
        longitud_slider=50.0,
        velocidad_agua=1.0,
        era='Era 1'
    )
    print(mensaje)

    print("\n--- Intento de creación de planta con campos correctos ---")
    mensaje = manager.crear_planta(
        id_planta=1,
        nombre='Tomate',
        fecha_plantacion=datetime(2023, 1, 1, 8, 0),
        angulo_h=30.0,
        angulo_y=0.0,
        longitud_slider=50.0,
        velocidad_agua=1.0,
        era='Era 1'
    )
    print(mensaje)

    print("\n--- Intento de creación de otra planta con todos los campos ---")
    mensaje = manager.crear_planta(
        id_planta=2,
        nombre='Lechuga',
        fecha_plantacion=datetime(2023, 2, 1, 9, 0),
        angulo_h=60.0,
        angulo_y=0.0,
        longitud_slider=70.0,
        velocidad_agua=0.8,
        era='Era 1'
    )
    print(mensaje)

    print("\n--- Intento de modificación de planta con atributo inválido ---")
    mensaje = manager.modificar_planta(
        id_planta=1,
        era='Era 1',
        color='Rojo'  # Atributo inválido
    )
    print(mensaje)

    print("\n--- Intento de modificación de planta con atributos válidos ---")
    mensaje = manager.modificar_planta(
        id_planta=1,
        era='Era 1',
        longitud_slider=55.0,  # Atributo válido
        velocidad_agua=1.2  # Atributo válido
    )
    print(mensaje)

    print("\n--- Intento de creación de régimen con campos faltantes ---")
    mensaje = manager.crear_regimen(
        id_planta=1,
        era='Era 1',
        id_regimen=1,
        nombre='Riego',
        descripcion='Regar cada 2 días',
        frecuencia=None,  # Campo faltante
        unidad_frecuencia='dias',
        fecha_inicio=datetime(2023, 1, 1)
    )
    print(mensaje)

    print("\n--- Intento de creación de régimen con todos los campos ---")
    mensaje = manager.crear_regimen(
        id_planta=1,
        era='Era 1',
        id_regimen=1,
        nombre='Riego',
        descripcion='Regar cada 2 días',
        frecuencia=2,
        unidad_frecuencia='dias',
        fecha_inicio=datetime(2023, 1, 1),
        fecha_fin=datetime(2023, 2, 1)
    )
    print(mensaje)

    print("\n--- Intento de modificación de régimen con atributo inválido ---")
    mensaje = manager.modificar_regimen(
        id_planta=1,
        era='Era 1',
        id_regimen=1,
        intervalo=3  # Atributo inválido
    )
    print(mensaje)

    print("\n--- Intento de modificación de régimen con atributos válidos ---")
    mensaje = manager.modificar_regimen(
        id_planta=1,
        era='Era 1',
        id_regimen=1,
        frecuencia=3,  # Atributo válido
        descripcion="Riego intensivo cada 3 días"
    )
    print(mensaje)

    print("\n--- Intento de creación de actividad con campos faltantes ---")
    mensaje = manager.crear_actividad(
        id_planta=1,
        era='Era 1',
        id_regimen=1,
        fecha=None,  # Campo faltante
        tipo_actividad='Fertilización',
        detalles='Aplicar fertilizante orgánico'
    )
    print(mensaje)

    print("\n--- Intento de creación de actividad con todos los campos ---")
    mensaje = manager.crear_actividad(
        id_planta=1,
        era='Era 1',
        id_regimen=1,
        fecha=datetime(2023, 1, 5, 8, 0),
        tipo_actividad='Fertilización',
        detalles='Aplicar fertilizante orgánico'
    )
    print(mensaje)

    print("\n--- Intento de modificación de actividad con fecha incorrecta ---")
    mensaje = manager.marcar_actividad_completada(
        id_planta=1,
        era='Era 1',
        id_regimen=1,
        fecha=datetime(2023, 1, 10, 8, 0)  # Fecha incorrecta
    )
    print(mensaje)

    print("\n--- Intento de marcar actividad existente como completada ---")
    mensaje = manager.marcar_actividad_completada(
        id_planta=1,
        era='Era 1',
        id_regimen=1,
        fecha=datetime(2023, 1, 5, 8, 0)
    )
    print(mensaje)

    print("\n--- Generar actividades automáticas para el régimen ---")
    manager.generar_actividades()

    print("\n--- Mostrar tareas de la planta 'Tomate' en la era 'Era 1' ---")
    manager.mostrar_tareas_de_planta(id_planta=1, era='Era 1')

    print("\n--- Verificar todas las posiciones de las plantas en la era 'Era 1' ---")
    mensaje = manager.mostrar_posiciones_de_plantas()
    print(mensaje)

    print("\n--- Intento de obtención de una planta no existente ---")
    mensaje = manager.obtener_planta(id_planta=3, era='Era 1')
    print(mensaje)

    print("\n--- Mostrar todas las eras disponibles ---")
    eras = list(manager.plantas_por_era.keys())
    print(f"Eras disponibles: {', '.join(eras)}")
