{# TRUE when a price is outside the plausible range (vars price_min / price_max). #}
{% macro out_of_bounds(col) -%}
coalesce({{ col }} not between {{ var('price_min') }} and {{ var('price_max') }}, false)
{%- endmacro %}
