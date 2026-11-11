{#
  Run at the start of every dbt run: expose the bronze Parquet under LAKE_ROOT as views in
  schema `bronze`, so sources are real relations (unit tests need their columns).
#}
{% macro register_bronze() -%}
create schema if not exists bronze;
create or replace view bronze.doe_prices as
select * from read_parquet(
    '{{ var("lake_root") }}/bronze/tables/doe_prices/**/*.parquet',
    hive_partitioning = true, union_by_name = true
);
create or replace view bronze.manifest as
select * from read_parquet('{{ var("lake_root") }}/bronze/manifest.parquet');
{%- endmacro %}
