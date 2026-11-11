{#
  Key form of a DOE name for the seed joins: upper case, whitespace collapsed to one
  space, blank -> NULL. The seeds store their keys in this form.
#}
{% macro normalize_name(column) -%}
nullif(upper(regexp_replace(trim({{ column }}), '\s+', ' ', 'g')), '')
{%- endmacro %}

{#
  Log each row of `sql` at info level (only when executing), so a failing test can show
  which values failed, e.g. names missing from a seed.
#}
{% macro log_rows(sql, label) -%}
{% if execute %}
  {% for row in run_query(sql) %}
    {% do log(label ~ ': ' ~ row.values() | join(' | '), info=True) %}
  {% endfor %}
{% endif %}
{%- endmacro %}
