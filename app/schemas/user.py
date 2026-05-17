from pydantic import BaseModel, ConfigDict, Field


class User(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., max_length=254)
    confirmed: bool = False


class UserCreateRequest(User):
    password: str = Field(..., min_length=8, max_length=128)


class Login(BaseModel):
    email: str = Field(..., max_length=254)
    password: str


class UsernameUpdate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)


class PasswordUpdate(BaseModel):
    current_password: str = Field(..., min_length=8, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(..., max_length=254)


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8, max_length=128)
