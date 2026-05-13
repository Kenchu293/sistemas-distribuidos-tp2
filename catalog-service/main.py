from fastapi import FastAPI, HTTPException

app = FastAPI(title="Catalog Service")

productos = [
    {"id": 1, "name": "Hollow Knight: Silksong", "price": 7},
    {"id": 2, "name": "Hunt: Showdown 1896", "price": 15},
    {"id": 3, "name": "ARC Raiders", "price": 40},
    {"id": 4, "name": "Age of Empires II: Definitive Edition", "price": 20},
]

@app.get("/conexion")
def conexion():
    return {"status": "ok", "service": "catalogo"}

@app.get("/productos")
def get_productos():
    return productos

@app.get("/productos/{product_id}")
def get_product(product_id: int):
    for product in productos:
        if product["id"] == product_id:
            return product
    raise HTTPException(status_code=404, detail="Producto no encontrado")