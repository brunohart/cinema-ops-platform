{% macro surrogate_key(field_list) -%}
  {#- Deterministic surrogate from natural-key parts. Not a source id. -#}
  md5(
    concat_ws(
      '||',
      {%- for field in field_list %}
      coalesce({{ field }}::text, '')
      {%- if not loop.last %},{% endif %}
      {%- endfor %}
    )
  )
{%- endmacro %}
