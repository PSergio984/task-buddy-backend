from pydantic import BaseModel


class User(BaseModel):
    id: int | None = None
    username: str
    email: str


class UserIn(User):
    password: str


class Login(BaseModel):
    email: str
    password: str
