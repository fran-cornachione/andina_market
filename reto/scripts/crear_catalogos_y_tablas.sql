-- Catálogo, Schema y Volúmen de la fuente simulada
CREATE CATALOG andina_source;
CREATE SCHEMA andina_source.landing;
CREATE VOLUME andina_source.landing.files;

-- Catálgo y Schemas Medallion
CREATE CATALOG andina_market;
CREATE SCHEMA andina_market.bronze;
CREATE SCHEMA andina_market.silver;
CREATE SCHEMA andina_market.gold;