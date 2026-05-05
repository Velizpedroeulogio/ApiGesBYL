# ============================================================
# AGREGAR ESTE CÓDIGO a ApiGesBYL_Servicio.py
# Endpoint /api/query — Ejecuta SQL libre y devuelve resultados
# ============================================================

from pydantic import BaseModel
from typing import Any, Optional
import traceback

# --- Modelo de entrada ---
class QueryRequest(BaseModel):
    sql: str

# --- Endpoint ---
@app.post("/api/query")
async def ejecutar_query(req: QueryRequest):
    """
    Ejecuta una consulta SQL libre contra la base PostgreSQL.
    - SELECT → devuelve columns + rows
    - INSERT / UPDATE / DELETE → devuelve affected (filas afectadas)
    """
    sql = req.sql.strip()
    if not sql:
        raise HTTPException(status_code=400, detail="La consulta SQL no puede estar vacía.")

    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur  = conn.cursor()
        cur.execute(sql)

        sql_upper = sql.upper().lstrip()

        if sql_upper.startswith("SELECT") or sql_upper.startswith("WITH"):
            # Consulta que devuelve filas
            cols = [desc[0] for desc in cur.description] if cur.description else []
            rows_raw = cur.fetchall()
            rows = []
            for row in rows_raw:
                row_dict = {}
                for i, col in enumerate(cols):
                    val = row[i]
                    # Convertir tipos no serializables
                    if hasattr(val, 'isoformat'):
                        val = val.isoformat()
                    elif hasattr(val, '__float__'):
                        val = float(val)
                    row_dict[col] = val
                rows.append(row_dict)
            conn.commit()
            return {"columns": cols, "rows": rows, "count": len(rows)}

        else:
            # INSERT / UPDATE / DELETE / DDL
            affected = cur.rowcount
            conn.commit()
            return {"affected": affected if affected >= 0 else 0, "message": "Operación ejecutada correctamente."}

    except psycopg2.Error as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=400, detail=f"Error PostgreSQL: {str(e)}")
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")
    finally:
        if conn:
            conn.close()
