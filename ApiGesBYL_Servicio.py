# Name:        ApiGesBYL_Servicio.py
# Purpose:     Servicio REST para INS / UPD / DLT / SEL sobre tablas controladas
# Author:      Pedro / Adaptado
#
# Instalacion:
#     pip install fastapi uvicorn psycopg2-binary
#
# Ejecucion:
#     uvicorn ApiGesBYL_Servicio:app --host 0.0.0.0 --port 8560
#
# Acciones soportadas:
#     INS  -> INSERT
#     UPD  -> UPDATE
#     DLT  -> DELETE
#     SEL  -> SELECT (devuelve lista de registros como diccionarios)
#
# Base de datos:
#     PostgreSQL remoto en Railway
#
# Cambios:
#     2026-05-04  get_conexion() simplificada: usa options="-c search_path=public"
#                 igual que test_pg.py que funciona correctamente.
#                 Se elimino el cursor anonimo + commit() que causaba problemas.
#

from fastapi import FastAPI
from pydantic import BaseModel
from typing import Dict, Any, Optional
import psycopg2
import psycopg2.extras
import hashlib
import json
import re

# --- Conexion PostgreSQL Railway ---
DATABASE_URL = "postgresql://postgres:EtSkpAxeGRBkLkdsKiQXrMIPJnuuKjlr@tramway.proxy.rlwy.net:56346/railway"

CLAVE_CRC = "CLAVE_SECRETA_ABG_2026"

TABLAS_PERMITIDAS = { "SOC_DEF",      "SUSCRIPTORES",
                      "INF_URL",      "PUB_DEF",
                      "EVNC_CAR",     "SORTEOS",        }

ACCIONES_VALIDAS = {"INS", "UPD", "DLT", "SEL"}

app = FastAPI(title="API Gestion BYL")


class ReqTabla(BaseModel):
    tabla:  str
    accion: str
    set:    Optional[Dict[str, Any]] = None
    where:  Optional[Dict[str, Any]] = None
    crc:    str


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def normalizar_tabla(tabla):
    return str(tabla or "").strip().upper()

def normalizar_accion(accion):
    return str(accion or "").strip().upper()

def validar_nombre_sql(nombre):
    txt = str(nombre or "").strip().upper()
    if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", txt):
        raise ValueError(f"Nombre SQL invalido: {nombre}")
    return txt

def json_ordenado(dic):
    return json.dumps( dic or {},           sort_keys=True,
                       ensure_ascii=False,  separators=(",", ":"), )

def calcular_crc(tabla, accion, set_data, where_data):
    tabla  = normalizar_tabla(tabla)
    accion = normalizar_accion(accion)
    base   = ( tabla  + "|" + accion + "|" +
               json_ordenado(set_data)   + "|" +
               json_ordenado(where_data) + "|" +
               CLAVE_CRC                        )
    return hashlib.sha256(base.encode("utf-8")).hexdigest()

def validar_crc(req):
    crc_calc = calcular_crc(req.tabla, req.accion, req.set, req.where)
    if str(req.crc or "").lower() != crc_calc.lower():
        raise ValueError("CRC invalido")

def armar_where(where_data, valores):
    if not where_data:
        raise ValueError("WHERE obligatorio")
    partes = []
    for campo, valor in where_data.items():
        campo_sql = validar_nombre_sql(campo)
        partes.append(f'"{campo_sql}" = %s')
        valores.append(valor)
    return " AND ".join(partes)


# ---------------------------------------------------------------------------
# CORRECCION 2026-05-04
# Antes: se usaba cursor anonimo + commit() dentro de get_conexion()
#        lo que dejaba la conexion en estado inconsistente.
# Ahora: se pasa search_path directamente en options= al conectar,
#        identico a como funciona test_pg.py.
# ---------------------------------------------------------------------------
def get_conexion():
    cnx = psycopg2.connect( DATABASE_URL,
                             connect_timeout=10,
                             options="-c search_path=public" )
    return cnx


# ---------------------------------------------------------------------------
# Ejecutores por accion
# ---------------------------------------------------------------------------

def ejecutar_insert(cur, tabla, set_data):
    if not set_data:
        raise ValueError("SET obligatorio para INS")
    campos  = []
    marcas  = []
    valores = []
    for campo, valor in set_data.items():
        campo_sql = validar_nombre_sql(campo)
        campos.append(f'"{campo_sql}"')
        marcas.append("%s")
        valores.append(valor)
    sql = ( f'INSERT INTO "{tabla}" '
            f'({", ".join(campos)}) '
            f'VALUES ({", ".join(marcas)})' )
    cur.execute(sql, valores)
    return sql, cur.rowcount

def ejecutar_update(cur, tabla, set_data, where_data):
    if not set_data:
        raise ValueError("SET obligatorio para UPD")
    valores    = []
    partes_set = []
    for campo, valor in set_data.items():
        campo_sql = validar_nombre_sql(campo)
        partes_set.append(f'"{campo_sql}" = %s')
        valores.append(valor)
    where_sql = armar_where(where_data, valores)
    sql = ( f'UPDATE "{tabla}" '
            f'SET {", ".join(partes_set)} '
            f'WHERE {where_sql}'            )
    cur.execute(sql, valores)
    return sql, cur.rowcount

def ejecutar_delete(cur, tabla, where_data):
    valores   = []
    where_sql = armar_where(where_data, valores)
    sql       = f'DELETE FROM "{tabla}" WHERE {where_sql}'
    cur.execute(sql, valores)
    return sql, cur.rowcount

def ejecutar_select(cur, tabla, where_data):
    """
    Recupera registros de cualquier tabla permitida.
    Devuelve lista de diccionarios {columna: valor}.
    WHERE es obligatorio para evitar selects masivos accidentales.
    """
    valores   = []
    where_sql = armar_where(where_data, valores)
    sql       = f'SELECT * FROM "{tabla}" WHERE {where_sql}'
    cur.execute(sql, valores)
    columnas  = [desc[0] for desc in cur.description]
    filas     = cur.fetchall()
    registros = [dict(zip(columnas, fila)) for fila in filas]
    return sql, registros


# ---------------------------------------------------------------------------
# Endpoint principal
# ---------------------------------------------------------------------------

@app.post("/api/tabla")
def api_tabla(req: ReqTabla):
    cnx = None
    try:
        tabla  = normalizar_tabla(req.tabla)
        accion = normalizar_accion(req.accion)

        print(f"\n>>> [{accion}] tabla={tabla}")
        if req.set:
            print(f"    SET  : {req.set}")
        if req.where:
            print(f"    WHERE: {req.where}")

        validar_nombre_sql(tabla)

        if tabla not in TABLAS_PERMITIDAS:
            return { "estado":  "ERROR",
                     "detalle": f"Tabla no permitida: {tabla}", }

        if accion not in ACCIONES_VALIDAS:
            return { "estado":  "ERROR",
                     "detalle": f"Accion invalida. Use: {', '.join(sorted(ACCIONES_VALIDAS))}", }

        validar_crc(req)

        cnx = get_conexion()
        cur = cnx.cursor()

        if accion == "INS":
            sql, afectados = ejecutar_insert(cur, tabla, req.set)
            cnx.commit()
            print(f"    >>> OK INS - registros afectados: {afectados}")
            return { "estado":    "OK",
                     "detalle":   "Proceso correcto",
                     "accion":    accion,
                     "tabla":     tabla,
                     "registros": afectados,
                     "sql":       sql,        }

        elif accion == "UPD":
            sql, afectados = ejecutar_update(cur, tabla, req.set, req.where)
            cnx.commit()
            print(f"    >>> OK UPD - registros afectados: {afectados}")
            return { "estado":    "OK",
                     "detalle":   "Proceso correcto",
                     "accion":    accion,
                     "tabla":     tabla,
                     "registros": afectados,
                     "sql":       sql,        }

        elif accion == "DLT":
            sql, afectados = ejecutar_delete(cur, tabla, req.where)
            cnx.commit()
            print(f"    >>> OK DLT - registros afectados: {afectados}")
            return { "estado":    "OK",
                     "detalle":   "Proceso correcto",
                     "accion":    accion,
                     "tabla":     tabla,
                     "registros": afectados,
                     "sql":       sql,        }

        else:  # SEL
            sql, registros = ejecutar_select(cur, tabla, req.where)
            print(f"    >>> OK SEL - registros encontrados: {len(registros)}")
            return { "estado":    "OK",
                     "detalle":   "Proceso correcto",
                     "accion":    accion,
                     "tabla":     tabla,
                     "registros": len(registros),
                     "datos":     registros,
                     "sql":       sql,          }

    except Exception as exc:
        print(f"    >>> ERROR: {exc}")
        if cnx is not None:
            try:
                cnx.rollback()
            except Exception:
                pass
        return { "estado":  "ERROR",
                 "detalle": str(exc), }

    finally:
        if cnx is not None:
            cnx.close()


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/")
def health():
    try:
        cnx = get_conexion()
        cnx.close()
        return {"estado": "OK", "db": "PostgreSQL Railway conectado"}
    except Exception as e:
        return {"estado": "ERROR", "detalle": str(e)}
