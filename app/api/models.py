"""Pydantic models for API request and response schemas."""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


# ─── Auth Models ─────────────────────────────────────────────────

class AuthRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6, max_length=128)


class SignupResponse(BaseModel):
    message: str
    user_id: str


class LoginResponse(BaseModel):
    token: str
    user_id: str


# ─── Document Models ────────────────────────────────────────────

class DocumentUploadResponse(BaseModel):
    message: str
    document_id: str
    status: str


class DocumentListItem(BaseModel):
    document_id: str
    filename: str
    upload_date: str
    status: str
    page_count: Optional[int] = None


class DocumentDeleteResponse(BaseModel):
    message: str
    document_id: str


# ─── Search Models ──────────────────────────────────────────────

class SearchResult(BaseModel):
    text: str
    score: float
    document_id: str
    filename: str


# ─── Error Models ───────────────────────────────────────────────

class ErrorResponse(BaseModel):
    error: str
