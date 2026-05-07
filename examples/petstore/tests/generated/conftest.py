# Scaffolded by pyoas — safe to edit; won't be overwritten unless tests.overwrite: true.
from __future__ import annotations

from polyfactory.factories.pydantic_factory import ModelFactory

from generated.models.pets import (
    Pet,
    PetList,
)
from generated.models.store import (
    Order,
)
from generated.models.users import (
    User,
)


class OrderFactory(ModelFactory):
    __model__ = Order


class PetFactory(ModelFactory):
    __model__ = Pet


class PetListFactory(ModelFactory):
    __model__ = PetList


class UserFactory(ModelFactory):
    __model__ = User


def make_order(**overrides) -> Order:
    """Minimal valid Order. Override fields as needed."""
    return OrderFactory.build(**overrides)


def make_pet(**overrides) -> Pet:
    """Minimal valid Pet. Override fields as needed."""
    return PetFactory.build(**overrides)


def make_pet_list(**overrides) -> PetList:
    """Minimal valid PetList. Override fields as needed."""
    return PetListFactory.build(**overrides)


def make_user(**overrides) -> User:
    """Minimal valid User. Override fields as needed."""
    return UserFactory.build(**overrides)
