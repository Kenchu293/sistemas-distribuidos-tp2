import asyncio
import grpc
import inventory_pb2
import inventory_pb2_grpc
from fastapi import FastAPI

app = FastAPI(title="Inventory Service")

stock = { 1: 5, 2: 20, 3: 40, 4: 12,}

class InventoryService(inventory_pb2_grpc.InventoryServiceServicer):
    async def ReserveStock(self, request, context):
        product_id = request.product_id
        quantity = request.quantity

        if product_id not in stock:
            return inventory_pb2.ReserveStockResponse(
                success=False,
                message="El Producto no Existe"
            )

        if stock[product_id] < quantity:
            return inventory_pb2.ReserveStockResponse(
                success=False,
                message="Stock insuficiente"
            )

        stock[product_id] -= quantity

        return inventory_pb2.ReserveStockResponse(
            success=True,
            message=f"Stock reservado. Stock restante: {stock[product_id]}"
        )

async def start_grpc_server():
    server = grpc.aio.server()
    inventory_pb2_grpc.add_InventoryServiceServicer_to_server(
        InventoryService(), server
    )
    server.add_insecure_port("[::]:50051")
    await server.start()
    await server.wait_for_termination()

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(start_grpc_server())

@app.get("/conexion")
def conexion():
    return {"status": "ok", "service": "inventorio"}

@app.get("/stock")
def get_stock():
    return stock