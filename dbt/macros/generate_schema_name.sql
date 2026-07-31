{% macro generate_schema_name(custom_schema_name, node) -%}
  {#- Custom schemas land as-is (silver, gold) — not target_schema_custom. -#}
  {%- if custom_schema_name is none -%}
    {{ target.schema }}
  {%- else -%}
    {{ custom_schema_name | trim }}
  {%- endif -%}
{%- endmacro %}
