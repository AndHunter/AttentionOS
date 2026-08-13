"""Design tokens for the native AttentionOS desktop UI."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Colors:
    background: str = "#F6F7F9"
    surface: str = "#FFFFFF"
    surface_secondary: str = "#F0F2F5"
    surface_hover: str = "#F8FAFB"
    border: str = "#E2E5E9"
    border_strong: str = "#CED3D9"
    text: str = "#16181D"
    text_secondary: str = "#69707D"
    text_tertiary: str = "#8C939D"
    accent: str = "#2F8F83"
    accent_hover: str = "#287C72"
    accent_soft: str = "#E4F3F0"
    success: str = "#3BA272"
    warning: str = "#D99A32"
    danger: str = "#D95C5C"
    idle: str = "#A8AFB8"
    overlay: str = "#E9ECEF"
    glow: str = "#DCEFEA"
    accent_text: str = "#FFFFFF"


LIGHT_COLORS = Colors()
DARK_COLORS = Colors(
    background="#0D1210",
    surface="#151B18",
    surface_secondary="#1B231F",
    surface_hover="#222C27",
    border="#25302B",
    border_strong="#34433D",
    text="#F4F7F5",
    text_secondary="#9BA8A1",
    text_tertiary="#68746E",
    accent="#9BE15D",
    accent_hover="#88CE50",
    accent_soft="#172815",
    success="#4BD38A",
    warning="#D6A84A",
    danger="#F07171",
    idle="#5E6963",
    overlay="#202A26",
    glow="#1D3818",
    accent_text="#0B120D",
)


@dataclass(frozen=True)
class Spacing:
    xxs: int = 4
    xs: int = 8
    sm: int = 12
    md: int = 16
    lg: int = 24
    xl: int = 32


@dataclass(frozen=True)
class Radius:
    sm: int = 8
    md: int = 12
    lg: int = 14


@dataclass(frozen=True)
class Typography:
    family: str = "Segoe UI Variable"
    fallback: str = "Segoe UI"
    display: tuple[str, int, str] = ("Segoe UI Variable", 42, "bold")
    page_title: tuple[str, int, str] = ("Segoe UI Variable", 30, "bold")
    section: tuple[str, int, str] = ("Segoe UI Variable", 18, "bold")
    metric: tuple[str, int, str] = ("Segoe UI Variable", 30, "bold")
    body: tuple[str, int] = ("Segoe UI Variable", 14)
    body_semibold: tuple[str, int, str] = ("Segoe UI Variable", 14, "bold")
    caption: tuple[str, int] = ("Segoe UI Variable", 12)
    caption_semibold: tuple[str, int, str] = ("Segoe UI Variable", 12, "bold")


COLORS = Colors()
SPACING = Spacing()
RADIUS = Radius()
TYPOGRAPHY = Typography()

APP_COLORS = [
    "#9BE15D",
    "#4BD38A",
    "#58A6FF",
    "#C8A2FF",
    "#D6A84A",
    "#7DD3C7",
    "#A8B3A6",
    "#F07171",
]


def apply_color_theme(theme: str) -> None:
    """Mutate shared color tokens so existing imports see the selected palette."""
    source = DARK_COLORS if theme == "dark" else LIGHT_COLORS
    for key, value in source.__dict__.items():
        setattr(COLORS, key, value)
