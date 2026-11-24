"""Registration and sign-in (OAuth2 password flow with a JWT bearer token)."""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session, select

from core.db import User
from core.i18n import msg

from ..schemas import Token, UserCreate, UserRead
from ..security import create_access_token, hash_password, verify_password
from ..state import get_lang, get_session

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED,
             summary="Create an account")
def register(body: UserCreate, session: Session = Depends(get_session), lang: str = Depends(get_lang)):
    email = body.email.lower()
    if session.exec(select(User).where(User.email == email)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, msg("auth.email_taken", lang))
    user = User(email=email, name=body.name.strip(), password_hash=hash_password(body.password))
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@router.post("/token", response_model=Token, summary="Sign in (form fields: username = e-mail, password)")
def login(form: OAuth2PasswordRequestForm = Depends(), session: Session = Depends(get_session),
          lang: str = Depends(get_lang)):
    """OAuth2 password flow, so the Authorize button in /docs works with the same endpoint."""
    user = session.exec(select(User).where(User.email == form.username.lower())).first()
    if user is None or not verify_password(form.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, msg("auth.bad_login", lang),
                            headers={"WWW-Authenticate": "Bearer"})
    return Token(access_token=create_access_token(user.id), user=UserRead.model_validate(user))
