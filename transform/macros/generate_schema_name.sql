{% macro generate_schema_name(custom_schema_name, node) -%}
  {#- Prefer the custom schema as written (silver, snapshots) rather than
      dbt's default target_schema_custom concatenation (silver_silver). -#}
  {%- if custom_schema_name is none -%}
    {{ target.schema }}
  {%- else -%}
    {{ custom_schema_name | trim }}
  {%- endif -%}
{%- endmacro %}
