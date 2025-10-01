-- Create blog categories
create table if not exists public.blog_categories (
  id bigserial primary key,
  name varchar not null,
  slug varchar not null,
  description text null,
  created_at timestamp without time zone default now(),
  updated_at timestamp without time zone null
);

create unique index if not exists ux_blog_categories_slug on public.blog_categories (slug);
create unique index if not exists ux_blog_categories_name on public.blog_categories (name);

-- Create blog tags
create table if not exists public.blog_tags (
  id bigserial primary key,
  name varchar not null,
  slug varchar not null,
  created_at timestamp without time zone default now(),
  updated_at timestamp without time zone null
);

create unique index if not exists ux_blog_tags_slug on public.blog_tags (slug);
create unique index if not exists ux_blog_tags_name on public.blog_tags (name);

-- Create blog posts
create table if not exists public.blog_posts (
  id bigserial primary key,
  title varchar not null,
  slug varchar not null,
  content text not null,
  excerpt text null,
  cover_image_url varchar null,
  author_id bigint references public.users(id) on delete set null,
  created_at timestamp without time zone default now(),
  updated_at timestamp without time zone null
);

create unique index if not exists ux_blog_posts_slug on public.blog_posts (slug);
create index if not exists ix_blog_posts_created_at on public.blog_posts (created_at);

-- Association: post -> category
create table if not exists public.blog_post_categories (
  id bigserial primary key,
  post_id bigint not null references public.blog_posts(id) on delete cascade,
  category_id bigint not null references public.blog_categories(id) on delete cascade,
  created_at timestamp without time zone default now()
);

create unique index if not exists ux_blog_post_category_unique on public.blog_post_categories (post_id, category_id);

-- Association: post -> tag
create table if not exists public.blog_post_tags (
  id bigserial primary key,
  post_id bigint not null references public.blog_posts(id) on delete cascade,
  tag_id bigint not null references public.blog_tags(id) on delete cascade,
  created_at timestamp without time zone default now()
);

create unique index if not exists ux_blog_post_tag_unique on public.blog_post_tags (post_id, tag_id);
