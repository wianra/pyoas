# Scaffolded by pyoas — safe to edit; won't be overwritten unless overwrite: true.
from __future__ import annotations

from typing import Literal

from fastapi import HTTPException
from generated.models.pets import CreatePetRequest, Pet, PetList, UpdatePetRequest

# In-memory store — replace with a real database session in production.
_store: dict[int, Pet] = {}
_next_id = 1


class PetsService:
    async def list_pets(
        self,
        *,
        limit: int | None = None,
        status: Literal["available", "pending", "sold"] | None = None,
    ) -> PetList:
        """List all pets"""
        pets = list(_store.values())
        if status is not None:
            pets = [p for p in pets if p.status == status]
        if limit is not None:
            pets = pets[:limit]
        return PetList(items=pets, total=len(pets))

    async def create_pet(
        self,
        *,
        body: CreatePetRequest,
    ) -> Pet:
        """Create a pet"""
        global _next_id
        pet = Pet(id=_next_id, name=body.name, tag=body.tag)
        _store[_next_id] = pet
        _next_id += 1
        return pet

    async def get_pet(
        self,
        *,
        pet_id: int,
    ) -> Pet:
        """Get a pet by ID"""
        pet = _store.get(pet_id)
        if pet is None:
            raise HTTPException(status_code=404, detail=f"Pet {pet_id} not found")
        return pet

    async def update_pet(
        self,
        *,
        pet_id: int,
        body: UpdatePetRequest,
    ) -> Pet:
        """Update a pet"""
        pet = _store.get(pet_id)
        if pet is None:
            raise HTTPException(status_code=404, detail=f"Pet {pet_id} not found")
        updated = pet.model_copy(
            update={k: v for k, v in body.model_dump().items() if v is not None}
        )
        _store[pet_id] = updated
        return updated

    async def delete_pet(
        self,
        *,
        pet_id: int,
    ) -> None:
        """Delete a pet"""
        if pet_id not in _store:
            raise HTTPException(status_code=404, detail=f"Pet {pet_id} not found")
        del _store[pet_id]


async def get_pets_service() -> PetsService:
    return PetsService()
