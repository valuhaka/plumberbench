"""The PlumberBench icon (a tap and a drop), shared by the website and the play page."""

ICON = """<svg viewBox="0 0 64 64" aria-hidden="true"><defs><linearGradient id="ICONID" x1="0" y1="0" x2="0" y2="1">
<stop offset="0" stop-color="#9fd0f5"/><stop offset="1" stop-color="#2f78c4"/></linearGradient></defs>
<path d="M10 18h22a10 10 0 0 1 10 10v8h-9v-6a3 3 0 0 0-3-3H10z" fill="#b9c2cc" stroke="#6b7682" stroke-width="1.5"/>
<rect x="7" y="15" width="5" height="15" rx="1.5" fill="#d7dde3" stroke="#6b7682" stroke-width="1.5"/>
<rect x="31" y="34" width="13" height="5" rx="1.5" fill="#d7dde3" stroke="#6b7682" stroke-width="1.5"/>
<path d="M37.5 42c4 6 7 9.5 7 13.2a7 7 0 0 1-14 0c0-3.7 3-7.2 7-13.2z" fill="url(#ICONID)" stroke="#1f5a99" stroke-width="1.2"/>
<path d="M34.5 54.5a3.5 3.5 0 0 0 3 3.2" stroke="#fff" stroke-opacity=".8" stroke-width="1.6" fill="none" stroke-linecap="round"/></svg>"""


def icon(gradient_id: str) -> str:
    """The icon as inline SVG; each copy on a page needs its own gradient id."""
    return ICON.replace("ICONID", gradient_id)
