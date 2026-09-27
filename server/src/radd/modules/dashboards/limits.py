"""The bounds a dashboard widget's geometry is validated against — one spelling,
shared by the create and update schemas. The dashboards UI mirrors these in
`ui/src/types.ts` (`WIDGET_LIMITS`), and `tests/test_dashboards.py` holds the two together."""

# Twelve-column layout, with a two-column minimum for legibility.
WIDGET_MIN_WIDTH = 2
WIDGET_MAX_WIDTH = 12
WIDGET_DEFAULT_WIDTH = 4
# Pixel heights: enough for one chart row, up to a tall list.
WIDGET_MIN_HEIGHT = 160
WIDGET_MAX_HEIGHT = 1600
WIDGET_DEFAULT_HEIGHT = 360
