-- NCR cities DOE monitors (eras B and C).
select distinct city from {{ ref('cities') }}
