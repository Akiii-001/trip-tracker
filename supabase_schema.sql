-- Trip price tracker schema. Run this in the Supabase SQL editor.

-- Singleton-ish trip configuration (keyed so you could store multiple trips).
create table if not exists trip_config (
    key        text primary key,
    config     jsonb not null,
    updated_at timestamptz not null default now()
);

-- Per-item tracking state used to decide alerts and avoid spam.
create table if not exists tracker_state (
    item_id        text primary key,   -- e.g. "flight:out", "hotel:havelock"
    lowest_price   double precision,
    last_price     double precision,
    target_alerted boolean default false,
    updated_at     timestamptz not null default now()
);

-- Append-only price log powering the history charts.
create table if not exists price_history (
    id          bigint generated always as identity primary key,
    trip        text,                  -- trip key (namespacing)
    item_id     text not null,
    item_type   text not null,         -- "flight" or "hotel"
    label       text,
    price       double precision not null,
    currency    text,
    source      text,                  -- cheapest booking site (hotels)
    island      text,                  -- island/area (hotels)
    rating      double precision,      -- Google rating (hotels)
    reviews     integer,               -- review count (hotels)
    total_price double precision,      -- full-stay price (hotels)
    checked_at  timestamptz not null default now()
);

create index if not exists price_history_item_idx
    on price_history (item_id, checked_at desc);
