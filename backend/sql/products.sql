-- Run this once in Supabase SQL Editor if the product catalog table does not exist.
-- CSV import headers:
-- sku,name_th,category,shade,price_thb,stock_qty
CREATE TABLE IF NOT EXISTS public.products (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    sku text NOT NULL UNIQUE,
    name_th text NOT NULL,
    category text NOT NULL,
    shade text,
    price_thb numeric(12, 2) NOT NULL CHECK (price_thb >= 0),
    stock_qty integer NOT NULL DEFAULT 0 CHECK (stock_qty >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Migrate the earlier generic schema without dropping existing product rows.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'products' AND column_name = 'name'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'products' AND column_name = 'name_th'
    ) THEN
        ALTER TABLE public.products RENAME COLUMN name TO name_th;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'products' AND column_name = 'color'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'products' AND column_name = 'shade'
    ) THEN
        ALTER TABLE public.products RENAME COLUMN color TO shade;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'products' AND column_name = 'price'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'products' AND column_name = 'price_thb'
    ) THEN
        ALTER TABLE public.products RENAME COLUMN price TO price_thb;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'products' AND column_name = 'stock'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'products' AND column_name = 'stock_qty'
    ) THEN
        ALTER TABLE public.products RENAME COLUMN stock TO stock_qty;
    END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS products_name_idx
    ON public.products (name_th);

CREATE INDEX IF NOT EXISTS products_sku_idx
    ON public.products (sku);

CREATE INDEX IF NOT EXISTS products_category_idx
    ON public.products (category);

CREATE INDEX IF NOT EXISTS products_shade_idx
    ON public.products (shade);

ALTER TABLE public.products ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "authenticated users can read products" ON public.products;
CREATE POLICY "authenticated users can read products"
    ON public.products
    FOR SELECT
    TO authenticated
    USING (true);

CREATE OR REPLACE FUNCTION public.set_products_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS products_set_updated_at ON public.products;
CREATE TRIGGER products_set_updated_at
    BEFORE UPDATE ON public.products
    FOR EACH ROW
    EXECUTE FUNCTION public.set_products_updated_at();
