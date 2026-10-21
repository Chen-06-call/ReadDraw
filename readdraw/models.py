"""Domain models shared by the UI and persistence layers."""

from dataclasses import dataclass


@dataclass
class Book:
    id: str
    title: str
    path: str
    pages: int
    current_page: int
    added_at: str
    format: str = "pdf"


@dataclass
class TextAnnotation:
    id: str
    book_id: str
    page: int
    kind: str
    content: str
    quote: str
    color: str
    created_at: str


@dataclass
class Attachment:
    id: str
    book_id: str
    page: int
    path: str
    name: str
    x: int
    y: int
    width: int
    height: int
    created_at: str
