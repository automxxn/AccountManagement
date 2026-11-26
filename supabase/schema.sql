-- AccountManagement 클라우드 DB 구조와 권한 규칙
-- Supabase 대시보드 → SQL Editor 에 이 파일 전체를 붙여넣고 Run 하세요. (여러 번 실행해도 안전합니다)
--
-- 원칙
--  * 테이블은 읽기만 RLS로 허용하고, 쓰기는 전부 아래 함수(RPC)로만 한다. 함수 안에서 권한을 검사한다.
--  * 첫 번째로 가입한 사용자가 총관리자가 되고, 이후 가입자는 '대기' 상태로 승인을 기다린다.
--  * 데이터(컴퓨터, 계정, 배정, 게임 종류, 변경 기록)는 팀별로 나뉜다. 다른 팀 데이터는 보이지 않는다.
--  * 권한 단계: 총관리자(모든 권한) > 관리자(맡은 팀들, 총관리자가 켜 준 권한 + 관리자 일) > 근무자(팀 1개, 켜 준 권한만)
--  * 비번 암호화 열쇠는 팀마다 다르다. 총관리자는 팀 암호로, 나머지는 각자 개인 열쇠로 받은 팀 열쇠로 푼다.

-- ============================================================ 테이블
create table if not exists public.profiles (
    id                  uuid primary key references auth.users(id) on delete cascade,
    login               text not null default '',
    display_name        text not null default '',
    role                text not null default 'pending',
    can_add_account     boolean not null default false,
    can_edit_account    boolean not null default false,
    can_delete_account  boolean not null default false,
    can_edit_pc         boolean not null default false,
    created_at          timestamptz not null default now()
);

alter table public.profiles add column if not exists can_view_workplace boolean not null default true;
alter table public.profiles add column if not exists can_view_accounts boolean not null default true;
-- 관리자에게만 의미 있음: 가입 승인과 팀 배정을 할 수 있는지 (총관리자가 켜 줌)
alter table public.profiles add column if not exists can_assign_team boolean not null default false;
-- PC 조종: LD CLOUD 실행기에 명령(시작/재시작/로그인 등)을 보내고 실행기 설정을 바꿀 수 있는지
alter table public.profiles add column if not exists can_control_pc boolean not null default false;
-- 컴퓨터 추가 / 삭제 (근무자에게 켜 줄 수 있음. 관리자는 맡은 팀에서 항상 가능)
alter table public.profiles add column if not exists can_add_pc boolean not null default false;
alter table public.profiles add column if not exists can_delete_pc boolean not null default false;

-- 팀: 이름, 게임 종류, 팀 열쇠 확인값(열쇠가 맞는지 확인하는 암호문)
create table if not exists public.teams (
    id          bigint generated always as identity primary key,
    name        text not null unique,
    games       jsonb not null default '["메랜","플래닛"]'::jsonb,
    key_check   text not null default '',
    created_at  timestamptz not null default now()
);

-- 팀 열쇠를 총관리자의 팀 암호로 잠근 것 (총관리자만 읽음)
create table if not exists public.team_master (
    team_id  bigint primary key references public.teams(id) on delete cascade,
    box      text not null
);

-- 누가 어느 팀에 속하는지 (근무자는 1개, 관리자는 여러 개)
create table if not exists public.team_members (
    team_id  bigint not null references public.teams(id) on delete cascade,
    user_id  uuid not null references public.profiles(id) on delete cascade,
    primary key (team_id, user_id)
);
create index if not exists team_members_user_idx on public.team_members(user_id);

-- 개인 열쇠: 공개 열쇠는 관리자가 팀 열쇠를 넘겨줄 때 쓴다
create table if not exists public.user_keys (
    user_id     uuid primary key references public.profiles(id) on delete cascade,
    public_key  text not null,
    updated_at  timestamptz not null default now()
);

-- 개인 열쇠(비공개)를 본인 로그인 비밀번호로 잠근 것 (본인만 읽음, 다른 PC에서 로그인할 때 필요)
create table if not exists public.user_secrets (
    user_id  uuid primary key references public.profiles(id) on delete cascade,
    salt     text not null default '',
    box      text not null default ''
);

-- 팀 열쇠를 각 사람의 공개 열쇠로 잠근 것 (그 사람만 풀 수 있음)
create table if not exists public.team_keys (
    team_id     bigint not null references public.teams(id) on delete cascade,
    user_id     uuid not null references public.profiles(id) on delete cascade,
    public_key  text not null,
    sealed      text not null,
    primary key (team_id, user_id)
);

create table if not exists public.pcs (
    id          bigint generated always as identity primary key,
    no          integer not null,
    name        text not null default '',
    remote_t    text not null default '',
    anydesk_id  text not null default '',
    anydesk_pw  text not null default '',   -- 앱에서 암호화한 값
    vpn         text not null default '',
    ld_cloud    text not null default '',
    slot_count  integer not null default 2 check (slot_count between 1 and 50),
    note        text not null default '',
    worker_id   uuid references public.profiles(id) on delete set null,
    version     integer not null default 1,
    updated_at  timestamptz not null default now()
);

create table if not exists public.accounts (
    id          bigint generated always as identity primary key,
    owner       text not null default '',
    contact     text not null default '',
    provider    text not null default '',
    login_id    text not null,
    login_key   text not null,
    password    text not null default '',   -- 앱에서 암호화한 값
    tag         text not null default '',
    mr_banned   boolean not null default false,
    mr_until    text not null default '',
    pl_banned   boolean not null default false,
    pl_until    text not null default '',
    withdrawn   boolean not null default false,
    note        text not null default '',
    worker_id   uuid references public.profiles(id) on delete set null,
    version     integer not null default 1,
    updated_at  timestamptz not null default now()
);

-- 인증불가: 아이디/비번은 있지만 인증을 못 해서 쓸 수 없는 계정 (탈퇴처럼 취급, 풀면 다시 사용)
alter table public.accounts add column if not exists auth_blocked boolean not null default false;
-- 메랜/플래닛 말고 나중에 추가한 게임의 정지 정보: {"게임이름": {"banned": true, "until": "2027-01-01 12:00"}}
alter table public.accounts add column if not exists other_bans jsonb not null default '{}'::jsonb;

-- 근무자가 삭제하면 바로 지우지 않고 '삭제 요청'으로 표시 → 관리자가 승인해야 진짜 삭제
alter table public.accounts add column if not exists delete_requested_at timestamptz;
alter table public.accounts add column if not exists delete_requested_by uuid references public.profiles(id) on delete set null;
alter table public.accounts add column if not exists delete_prev_pc bigint;
alter table public.accounts add column if not exists delete_prev_slot integer;

create table if not exists public.characters (
    id          bigint generated always as identity primary key,
    account_id  bigint not null references public.accounts(id) on delete cascade,
    game        text not null,
    nickname    text not null default '',
    level_job   text not null default '',
    sort        integer not null default 0
);
create index if not exists characters_account_idx on public.characters(account_id);

-- 게임 종류는 관리자가 추가할 수 있으므로 이전에 걸어 둔 제한을 푼다
alter table public.characters drop constraint if exists characters_game_check;

create table if not exists public.assignments (
    pc_id       bigint not null references public.pcs(id) on delete cascade,
    slot        integer not null,
    account_id  bigint not null unique references public.accounts(id) on delete cascade,
    assigned_at timestamptz not null default now(),
    primary key (pc_id, slot)
);

create table if not exists public.audit_log (
    id        bigint generated always as identity primary key,
    at        timestamptz not null default now(),
    actor_id  uuid,
    actor     text not null default '',
    action    text not null,
    detail    text not null default ''
);

create table if not exists public.app_settings (
    key    text primary key,
    value  text not null
);

-- ============================================================ 팀 나누기 (예전 데이터 옮기기)
-- 역할: 가장 먼저 가입한 관리자를 총관리자로
alter table public.profiles drop constraint if exists profiles_role_check;
update public.profiles set role = 'super'
 where id = (select id from public.profiles where role = 'admin' order by created_at limit 1)
   and not exists (select 1 from public.profiles where role = 'super');
alter table public.profiles add constraint profiles_role_check check (role in ('super', 'admin', 'worker', 'pending', 'agent'));

-- 팀이 하나도 없으면 '1팀'을 만들고 지금 게임 종류와 팀 암호 확인값을 그대로 쓴다
insert into public.teams (name, games, key_check)
select '1팀',
       coalesce((select value::jsonb from public.app_settings where key = 'games'), '["메랜","플래닛"]'::jsonb),
       coalesce((select value from public.app_settings where key = 'key_check'), '')
where not exists (select 1 from public.teams);

alter table public.pcs add column if not exists team_id bigint references public.teams(id);
alter table public.accounts add column if not exists team_id bigint references public.teams(id);
alter table public.audit_log add column if not exists team_id bigint;

update public.pcs set team_id = (select min(id) from public.teams) where team_id is null;
update public.accounts set team_id = (select min(id) from public.teams) where team_id is null;
alter table public.pcs alter column team_id set not null;
alter table public.accounts alter column team_id set not null;

do $$
begin
    if not exists (select 1 from public.app_settings where key = 'migrated_teams') then
        -- 예전 변경 기록과 예전 근무자는 1팀으로
        update public.audit_log set team_id = (select min(id) from public.teams) where team_id is null;
        insert into public.team_members (team_id, user_id)
        select (select min(id) from public.teams), id from public.profiles where role in ('admin', 'worker')
        on conflict do nothing;
        insert into public.app_settings (key, value) values ('migrated_teams', '1');
    end if;
end $$;

-- 번호와 아이디는 팀 안에서만 겹치면 안 된다
alter table public.pcs drop constraint if exists pcs_no_key;
create unique index if not exists pcs_team_no_idx on public.pcs(team_id, no);
alter table public.accounts drop constraint if exists accounts_provider_login_key_key;
create unique index if not exists accounts_team_login_idx on public.accounts(team_id, provider, login_key);
create index if not exists pcs_team_idx on public.pcs(team_id);
create index if not exists accounts_team_idx on public.accounts(team_id);
create index if not exists audit_team_idx on public.audit_log(team_id, id);

-- ============================================================ 가입 시 프로필 자동 생성
create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
    insert into public.profiles (id, login, display_name, role,
                                 can_add_account, can_edit_account, can_delete_account, can_edit_pc)
    values (new.id,
            coalesce(new.email, ''),
            coalesce(nullif(new.raw_user_meta_data ->> 'display_name', ''), split_part(coalesce(new.email, ''), '@', 1)),
            case when coalesce(new.raw_user_meta_data ->> 'kind', '') = 'agent' then 'agent'
                 when exists (select 1 from public.profiles where role = 'super') then 'pending' else 'super' end,
            false, false, false, false)
    on conflict (id) do nothing;
    return new;
end $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users
    for each row execute function public.handle_new_user();

-- ============================================================ 권한 도우미
create or replace function public.my_role() returns text
language sql stable security definer set search_path = public as $$
    select role from profiles where id = auth.uid()
$$;

create or replace function public.is_super() returns boolean
language sql stable security definer set search_path = public as $$
    select coalesce(my_role() = 'super', false)
$$;

-- 총관리자 또는 관리자
create or replace function public.is_admin() returns boolean
language sql stable security definer set search_path = public as $$
    select coalesce(my_role() in ('super', 'admin'), false)
$$;

create or replace function public.is_member() returns boolean
language sql stable security definer set search_path = public as $$
    select coalesce(my_role() in ('super', 'admin', 'worker'), false)
$$;

-- 이 팀 데이터를 볼 수 있는 사람인지 (총관리자는 모든 팀)
create or replace function public.in_team(t bigint) returns boolean
language sql stable security definer set search_path = public as $$
    select is_super() or (coalesce(my_role() in ('admin', 'worker'), false)
        and exists (select 1 from team_members where team_id = t and user_id = auth.uid()))
$$;

-- 이 팀을 관리하는 사람인지 (총관리자, 또는 이 팀을 맡은 관리자)
create or replace function public.is_team_admin(t bigint) returns boolean
language sql stable security definer set search_path = public as $$
    select is_super() or (coalesce(my_role() = 'admin', false)
        and exists (select 1 from team_members where team_id = t and user_id = auth.uid()))
$$;

-- 총관리자는 전부, 관리자와 근무자는 켜 준 권한만
create or replace function public.has_perm(perm_name text) returns boolean
language sql stable security definer set search_path = public as $$
    select coalesce((
        select case
            when pr.role = 'super' then true
            when pr.role not in ('admin', 'worker') then false
            when perm_name = 'assign_team' then pr.role = 'admin' and pr.can_assign_team
            when perm_name = 'add_account' then pr.can_add_account
            when perm_name = 'edit_account' then pr.can_edit_account
            when perm_name = 'delete_account' then pr.can_delete_account
            when perm_name = 'edit_pc' then pr.can_edit_pc
            when perm_name = 'view_workplace' then pr.can_view_workplace
            when perm_name = 'view_accounts' then pr.can_view_accounts
            when perm_name = 'control_pc' then pr.can_control_pc
            when perm_name = 'add_pc' then pr.role = 'admin' or pr.can_add_pc
            when perm_name = 'delete_pc' then pr.role = 'admin' or pr.can_delete_pc
            else false end
        from profiles pr where pr.id = auth.uid()), false)
$$;

-- 계정 행을 볼 수 있는지: 같은 팀 + 작업장 보기나 계정 보기 권한 (삭제 요청 중인 계정은 관리자만)
create or replace function public._acc_visible(t bigint, del timestamptz) returns boolean
language sql stable security definer set search_path = public as $$
    select is_super() or (in_team(t) and (has_perm('view_workplace') or has_perm('view_accounts'))
                          and (del is null or my_role() = 'admin'))
$$;

create or replace function public.can_see_account(a_id bigint) returns boolean
language sql stable security definer set search_path = public as $$
    select exists (select 1 from accounts a where a.id = a_id and _acc_visible(a.team_id, a.delete_requested_at))
$$;

create or replace function public._pc_visible(t bigint) returns boolean
language sql stable security definer set search_path = public as $$
    select is_super() or (in_team(t) and has_perm('view_workplace'))
$$;

create or replace function public.owns_pc(p_id bigint) returns boolean
language sql stable security definer set search_path = public as $$
    select exists (select 1 from pcs where id = p_id and _pc_visible(team_id))
$$;

-- 이 사람이 나와 같은 팀에 있는지 (관리자가 근무자 목록과 공개 열쇠를 볼 때)
create or replace function public._shares_team(u uuid) returns boolean
language sql stable security definer set search_path = public as $$
    select exists (select 1 from team_members m1 join team_members m2 on m1.team_id = m2.team_id
                   where m1.user_id = auth.uid() and m2.user_id = u)
$$;

create or replace function public._can_see_profile(u uuid) returns boolean
language sql stable security definer set search_path = public as $$
    select u = auth.uid() or is_super()
        or (coalesce(my_role() = 'admin', false)
            and (_shares_team(u)
                 or (has_perm('assign_team') and exists (select 1 from profiles where id = u and role = 'pending'))))
$$;

-- ============================================================ 읽기 권한 (RLS)
alter table public.profiles      enable row level security;
alter table public.teams         enable row level security;
alter table public.team_master   enable row level security;
alter table public.team_members  enable row level security;
alter table public.user_keys     enable row level security;
alter table public.user_secrets  enable row level security;
alter table public.team_keys     enable row level security;
alter table public.pcs           enable row level security;
alter table public.accounts      enable row level security;
alter table public.characters    enable row level security;
alter table public.assignments   enable row level security;
alter table public.audit_log     enable row level security;
alter table public.app_settings  enable row level security;

drop policy if exists profiles_read on public.profiles;
create policy profiles_read on public.profiles for select to authenticated
    using (_can_see_profile(id));

drop policy if exists teams_read on public.teams;
create policy teams_read on public.teams for select to authenticated
    using (in_team(id));

drop policy if exists team_master_read on public.team_master;
create policy team_master_read on public.team_master for select to authenticated
    using (is_super());

drop policy if exists team_members_read on public.team_members;
create policy team_members_read on public.team_members for select to authenticated
    using (user_id = auth.uid() or is_team_admin(team_id));

drop policy if exists user_keys_read on public.user_keys;
create policy user_keys_read on public.user_keys for select to authenticated
    using (_can_see_profile(user_id));

drop policy if exists user_secrets_read on public.user_secrets;
create policy user_secrets_read on public.user_secrets for select to authenticated
    using (user_id = auth.uid());

drop policy if exists team_keys_read on public.team_keys;
create policy team_keys_read on public.team_keys for select to authenticated
    using (user_id = auth.uid() or is_team_admin(team_id));

drop policy if exists pcs_read on public.pcs;
create policy pcs_read on public.pcs for select to authenticated
    using (_pc_visible(team_id));

drop policy if exists accounts_read on public.accounts;
create policy accounts_read on public.accounts for select to authenticated
    using (_acc_visible(team_id, delete_requested_at));

drop policy if exists characters_read on public.characters;
create policy characters_read on public.characters for select to authenticated
    using (can_see_account(account_id));

drop policy if exists assignments_read on public.assignments;
create policy assignments_read on public.assignments for select to authenticated
    using (owns_pc(pc_id));

drop policy if exists audit_read on public.audit_log;
create policy audit_read on public.audit_log for select to authenticated
    using (is_super() or actor_id = auth.uid() or (team_id is not null and is_team_admin(team_id)));

-- 팀 암호 정보는 총관리자만
drop policy if exists settings_read on public.app_settings;
create policy settings_read on public.app_settings for select to authenticated
    using (is_super());

-- 쓰기 정책은 일부러 만들지 않는다 → 테이블 직접 수정 불가, 아래 함수로만 가능

-- ============================================================ 내부 도우미
drop function if exists public._log(text, text);
create or replace function public._log(p_action text, p_detail text, p_team bigint default null) returns void
language sql security definer set search_path = public as $$
    insert into audit_log (actor_id, actor, action, detail, team_id)
    select auth.uid(), coalesce((select display_name from profiles where id = auth.uid()), '?'), p_action, p_detail, p_team
$$;

create or replace function public._acc_label(a_id bigint) returns text
language sql stable security definer set search_path = public as $$
    select coalesce((select format('[%s] %s (%s)', provider, login_id, owner) from accounts where id = a_id), '계정#' || a_id)
$$;

create or replace function public._pc_label(p_id bigint, p_slot integer) returns text
language sql stable security definer set search_path = public as $$
    select coalesce((select format('%s번 컴퓨터 %s자리', no, p_slot) from pcs where id = p_id), '컴퓨터#' || p_id)
$$;

create or replace function public._pc_no_label(p_id bigint) returns text
language sql stable security definer set search_path = public as $$
    select coalesce((select format('%s번 컴퓨터', no) from pcs where id = p_id), '컴퓨터#' || p_id)
$$;

create or replace function public._team_name(t bigint) returns text
language sql stable security definer set search_path = public as $$
    select coalesce((select name from teams where id = t), '팀#' || t)
$$;

-- ============================================================ 계정
create or replace function public.save_account(p jsonb) returns bigint
language plpgsql security definer set search_path = public as $$
declare
    v_id      bigint := nullif(p ->> 'id', '')::bigint;
    v_team    bigint := nullif(p ->> 'team_id', '')::bigint;
    v_key     text := lower(trim(coalesce(p ->> 'login_id', '')));
    v_prov    text := trim(coalesce(p ->> 'provider', ''));
    v_cur     accounts%rowtype;
    c         jsonb;
    i         integer := 0;
begin
    if not is_member() then raise exception '권한이 없어요. 관리자 승인을 기다려 주세요.'; end if;
    if v_key = '' then raise exception '아이디를 입력하세요.'; end if;

    if v_id is null then
        if v_team is null or not in_team(v_team) then raise exception '이 팀에 계정을 추가할 수 없어요.'; end if;
        if not has_perm('add_account') then raise exception '계정 추가 권한이 없어요.'; end if;
    else
        select * into v_cur from accounts where id = v_id for update;
        if not found then raise exception '없는 계정이에요. 새로고침한 뒤 다시 시도하세요.'; end if;
        v_team := v_cur.team_id;
        if not (can_see_account(v_id) and has_perm('edit_account')) then
            raise exception '이 계정을 수정할 권한이 없어요.';
        end if;
        if v_cur.version <> coalesce((p ->> 'version')::integer, -1) then
            raise exception '다른 사람이 먼저 이 계정을 수정했어요. 새로고침한 뒤 다시 수정하세요.';
        end if;
    end if;

    if exists (select 1 from accounts where team_id = v_team and provider = v_prov and login_key = v_key
               and id is distinct from v_id and delete_requested_at is not null) then
        raise exception '같은 아이디가 삭제 요청 중이에요. 관리자가 승인하거나 거절한 뒤 다시 시도하세요.';
    end if;
    if exists (select 1 from accounts where team_id = v_team and provider = v_prov and login_key = v_key
               and id is distinct from v_id) then
        raise exception '같은 아이디가 이미 등록돼 있어요: [%] %', v_prov, trim(p ->> 'login_id');
    end if;

    if v_id is null then
        insert into accounts (team_id, owner, contact, provider, login_id, login_key, password, tag,
                              mr_banned, mr_until, pl_banned, pl_until, withdrawn, note,
                              auth_blocked, other_bans)
        values (v_team, trim(coalesce(p ->> 'owner', '')), trim(coalesce(p ->> 'contact', '')), v_prov,
                trim(p ->> 'login_id'), v_key, coalesce(p ->> 'password', ''), trim(coalesce(p ->> 'tag', '')),
                coalesce((p ->> 'mr_banned')::boolean, false), coalesce(p ->> 'mr_until', ''),
                coalesce((p ->> 'pl_banned')::boolean, false), coalesce(p ->> 'pl_until', ''),
                coalesce((p ->> 'withdrawn')::boolean, false), coalesce(p ->> 'note', ''),
                coalesce((p ->> 'auth_blocked')::boolean, false), coalesce(p -> 'other_bans', '{}'::jsonb))
        returning id into v_id;
        perform _log('계정 추가', _acc_label(v_id), v_team);
    else
        update accounts set
            owner = trim(coalesce(p ->> 'owner', '')), contact = trim(coalesce(p ->> 'contact', '')),
            provider = v_prov, login_id = trim(p ->> 'login_id'), login_key = v_key,
            password = coalesce(p ->> 'password', ''), tag = trim(coalesce(p ->> 'tag', '')),
            mr_banned = coalesce((p ->> 'mr_banned')::boolean, false), mr_until = coalesce(p ->> 'mr_until', ''),
            pl_banned = coalesce((p ->> 'pl_banned')::boolean, false), pl_until = coalesce(p ->> 'pl_until', ''),
            withdrawn = coalesce((p ->> 'withdrawn')::boolean, false), note = coalesce(p ->> 'note', ''),
            auth_blocked = coalesce((p ->> 'auth_blocked')::boolean, false),
            other_bans = coalesce(p -> 'other_bans', '{}'::jsonb),
            version = version + 1, updated_at = now()
        where id = v_id;
        perform _log('계정 수정', _acc_label(v_id), v_team);
    end if;

    delete from characters where account_id = v_id;
    for c in select * from jsonb_array_elements(coalesce(p -> 'characters', '[]'::jsonb)) loop
        if trim(coalesce(c ->> 'nickname', '')) <> '' or trim(coalesce(c ->> 'level_job', '')) <> '' then
            insert into characters (account_id, game, nickname, level_job, sort)
            values (v_id, c ->> 'game', trim(coalesce(c ->> 'nickname', '')), trim(coalesce(c ->> 'level_job', '')), i);
            i := i + 1;
        end if;
    end loop;

    if coalesce((p ->> 'withdrawn')::boolean, false) or coalesce((p ->> 'auth_blocked')::boolean, false) then
        delete from assignments where account_id = v_id;
    end if;
    return v_id;
end $$;

-- 관리자(삭제 권한이 있을 때)는 바로 삭제, 근무자는 삭제 요청
create or replace function public.delete_account(p_id bigint) returns void
language plpgsql security definer set search_path = public as $$
declare
    v_label text;
    v_team  bigint;
    v_where record;
begin
    select team_id into v_team from accounts where id = p_id;
    if not found then raise exception '없는 계정이에요. 새로고침하세요.'; end if;
    if not (can_see_account(p_id) and has_perm('delete_account')) then
        raise exception '이 계정을 삭제할 권한이 없어요.';
    end if;
    v_label := _acc_label(p_id);
    if is_team_admin(v_team) then
        delete from accounts where id = p_id;
        perform _log('계정 삭제', v_label, v_team);
        return;
    end if;
    -- 근무자: 삭제 요청으로 표시하고 자리에서 뺀다 (거절되면 비어 있을 때 원래 자리로 돌아감)
    select pc_id, slot into v_where from assignments where account_id = p_id;
    update accounts set delete_requested_at = now(), delete_requested_by = auth.uid(),
        delete_prev_pc = v_where.pc_id, delete_prev_slot = v_where.slot,
        version = version + 1, updated_at = now()
    where id = p_id;
    delete from assignments where account_id = p_id;
    perform _log('삭제 요청', v_label, v_team);
end $$;

create or replace function public.approve_delete(p_id bigint) returns void
language plpgsql security definer set search_path = public as $$
declare
    v_label text;
    v_team  bigint;
begin
    select team_id into v_team from accounts where id = p_id and delete_requested_at is not null;
    if not found then raise exception '삭제 요청이 없는 계정이에요. 새로고침하세요.'; end if;
    if not is_team_admin(v_team) then raise exception '관리자만 할 수 있어요.'; end if;
    v_label := _acc_label(p_id);
    delete from accounts where id = p_id;
    perform _log('삭제 승인', v_label, v_team);
end $$;

create or replace function public.reject_delete(p_id bigint) returns void
language plpgsql security definer set search_path = public as $$
declare
    v_acc  accounts%rowtype;
    v_back text := '';
begin
    select * into v_acc from accounts where id = p_id and delete_requested_at is not null;
    if not found then raise exception '삭제 요청이 없는 계정이에요. 새로고침하세요.'; end if;
    if not is_team_admin(v_acc.team_id) then raise exception '관리자만 할 수 있어요.'; end if;
    update accounts set delete_requested_at = null, delete_requested_by = null,
        delete_prev_pc = null, delete_prev_slot = null, version = version + 1, updated_at = now()
    where id = p_id;
    -- 원래 자리가 아직 비어 있으면 되돌려 놓는다
    if v_acc.delete_prev_pc is not null
       and exists (select 1 from pcs where id = v_acc.delete_prev_pc and team_id = v_acc.team_id
                   and slot_count >= v_acc.delete_prev_slot)
       and not exists (select 1 from assignments where pc_id = v_acc.delete_prev_pc and slot = v_acc.delete_prev_slot) then
        begin
            perform _check_owner_rule(p_id, v_acc.delete_prev_pc);
            insert into assignments (pc_id, slot, account_id) values (v_acc.delete_prev_pc, v_acc.delete_prev_slot, p_id);
            v_back := ' (원래 자리 ' || _pc_label(v_acc.delete_prev_pc, v_acc.delete_prev_slot) || '로 되돌림)';
        exception when others then
            v_back := ' (원래 자리로는 못 돌아감)';
        end;
    end if;
    perform _log('삭제 거절', _acc_label(p_id) || v_back, v_acc.team_id);
end $$;

-- ============================================================ 컴퓨터
create or replace function public.save_pc(p jsonb) returns bigint
language plpgsql security definer set search_path = public as $$
declare
    v_id     bigint := nullif(p ->> 'id', '')::bigint;
    v_team   bigint := nullif(p ->> 'team_id', '')::bigint;
    v_no     integer := (p ->> 'no')::integer;
    v_slots  integer := coalesce((p ->> 'slot_count')::integer, 2);
    v_cur    pcs%rowtype;
    v_over   text;
begin
    if v_slots < 1 then raise exception '자리 수는 1 이상이어야 해요.'; end if;
    if v_id is null then
        if v_team is null or not (is_team_admin(v_team) or (in_team(v_team) and has_perm('add_pc'))) then
            raise exception '컴퓨터 추가 권한이 없어요.';
        end if;
    else
        select * into v_cur from pcs where id = v_id for update;
        if not found then raise exception '없는 컴퓨터예요. 새로고침한 뒤 다시 시도하세요.'; end if;
        v_team := v_cur.team_id;
        if not (owns_pc(v_id) and has_perm('edit_pc')) then
            raise exception '이 컴퓨터 정보를 수정할 권한이 없어요.';
        end if;
        if v_cur.version <> coalesce((p ->> 'version')::integer, -1) then
            raise exception '다른 사람이 먼저 이 컴퓨터 정보를 수정했어요. 새로고침한 뒤 다시 수정하세요.';
        end if;
        select string_agg(slot || '자리', ', ' order by slot) into v_over
            from assignments where pc_id = v_id and slot > v_slots;
        if v_over is not null then
            raise exception '줄이려는 자리에 계정이 들어 있어요. 먼저 그 계정을 빼세요: %', v_over;
        end if;
    end if;
    if exists (select 1 from pcs where team_id = v_team and no = v_no and id is distinct from v_id) then
        raise exception '%번 컴퓨터가 이미 있어요.', v_no;
    end if;

    if v_id is null then
        insert into pcs (team_id, no, name, remote_t, anydesk_id, anydesk_pw, vpn, ld_cloud, slot_count, note)
        values (v_team, v_no, trim(coalesce(p ->> 'name', '')), trim(coalesce(p ->> 'remote_t', '')),
                trim(coalesce(p ->> 'anydesk_id', '')), coalesce(p ->> 'anydesk_pw', ''), trim(coalesce(p ->> 'vpn', '')),
                '', v_slots, coalesce(p ->> 'note', ''))
        returning id into v_id;
        perform _log('컴퓨터 추가', format('%s. %s', v_no, p ->> 'name'), v_team);
    else
        update pcs set no = v_no, name = trim(coalesce(p ->> 'name', '')), remote_t = trim(coalesce(p ->> 'remote_t', '')),
            anydesk_id = trim(coalesce(p ->> 'anydesk_id', '')), anydesk_pw = coalesce(p ->> 'anydesk_pw', ''),
            vpn = trim(coalesce(p ->> 'vpn', '')),   -- ld_cloud는 실행기가 정함
            slot_count = v_slots, note = coalesce(p ->> 'note', ''),
            version = version + 1, updated_at = now()
        where id = v_id;
        perform _log('컴퓨터 수정', format('%s. %s', v_no, p ->> 'name'), v_team);
    end if;
    return v_id;
end $$;

create or replace function public.delete_pc(p_id bigint) returns void
language plpgsql security definer set search_path = public as $$
declare
    v_label text;
    v_team  bigint;
begin
    select format('%s. %s', no, name), team_id into v_label, v_team from pcs where id = p_id;
    if not found then raise exception '없는 컴퓨터예요. 새로고침하세요.'; end if;
    if not (is_team_admin(v_team) or (in_team(v_team) and has_perm('delete_pc'))) then
        raise exception '컴퓨터 삭제 권한이 없어요.';
    end if;
    delete from pcs where id = p_id;
    perform _log('컴퓨터 삭제', coalesce(v_label, '') || ' (들어 있던 계정은 사용가능으로 돌아감)', v_team);
end $$;

-- 두 컴퓨터의 번호를 서로 바꾸기 (자리 계정, 컴퓨터 정보, 실행기 연결은 각 컴퓨터에 그대로 붙어서 함께 움직임)
create or replace function public.swap_pc_numbers(p_a bigint, p_b bigint) returns void
language plpgsql security definer set search_path = public as $$
declare
    a   pcs%rowtype;
    b   pcs%rowtype;
    tmp integer;
begin
    select * into a from pcs where id = p_a for update;
    select * into b from pcs where id = p_b for update;
    if a.id is null or b.id is null then raise exception '없는 컴퓨터예요. 새로고침하세요.'; end if;
    if a.id = b.id then raise exception '다른 컴퓨터를 고르세요.'; end if;
    if a.team_id <> b.team_id then raise exception '같은 팀 컴퓨터끼리만 바꿀 수 있어요.'; end if;
    if not (owns_pc(p_a) and has_perm('edit_pc')) then raise exception '컴퓨터 정보 수정 권한이 없어요.'; end if;
    select coalesce(min(no), 0) - 1 into tmp from pcs where team_id = a.team_id;   -- 잠깐 비켜 둘 번호
    update pcs set no = tmp where id = a.id;
    update pcs set no = a.no, version = version + 1, updated_at = now() where id = b.id;
    update pcs set no = b.no, version = version + 1, updated_at = now() where id = a.id;
    perform _log('컴퓨터 번호 바꾸기', format('%s. %s ↔ %s. %s (이제 %s번 = %s, %s번 = %s)',
        a.no, a.name, b.no, b.name, a.no, b.name, b.no, a.name), a.team_id);
end $$;

-- ============================================================ 명의자 규칙
-- 같은 명의자 계정은 팀 작업장 전체에 최대 2개까지, 그리고 그 2개는 같은 컴퓨터에만 넣을 수 있다.
-- 명의자 이름이 비어 있으면 연락처로 판단하고, 둘 다 없으면 규칙을 적용하지 않는다.
create or replace function public._owner_key(p_owner text, p_contact text) returns text
language sql immutable as $$
    select coalesce(nullif(trim(coalesce(p_owner, '')), ''), nullif(trim(coalesce(p_contact, '')), ''))
$$;

create or replace function public._check_owner_rule(p_account bigint, p_pc bigint) returns void
language plpgsql security definer set search_path = public as $$
declare
    v_key   text;
    v_team  bigint;
    v_cnt   integer;
    v_other bigint;
begin
    select _owner_key(owner, contact), team_id into v_key, v_team from accounts where id = p_account;
    if v_key is null then
        return;
    end if;
    select count(*), min(s.pc_id) filter (where s.pc_id <> p_pc)
      into v_cnt, v_other
      from assignments s join accounts a on a.id = s.account_id
     where a.id <> p_account and a.team_id = v_team and _owner_key(a.owner, a.contact) = v_key;
    if v_cnt >= 2 then
        raise exception '명의자 ''%''의 계정이 이미 %개 들어가 있어요. 같은 명의 계정은 최대 2개까지예요.', v_key, v_cnt;
    end if;
    if v_other is not null then
        raise exception '명의자 ''%''의 계정이 이미 %번 컴퓨터에 있어요. 같은 명의 계정은 같은 컴퓨터에만 넣을 수 있어요.',
            v_key, (select no from pcs where id = v_other);
    end if;
end $$;

-- ============================================================ 배정
create or replace function public.assign_account(p_pc bigint, p_slot integer, p_account bigint) returns void
language plpgsql security definer set search_path = public as $$
declare
    v_pc  pcs%rowtype;
    v_acc accounts%rowtype;
    v_where record;
begin
    select * into v_pc from pcs where id = p_pc;
    if not found or p_slot < 1 or p_slot > v_pc.slot_count then
        raise exception '없는 자리예요. 새로고침한 뒤 다시 시도하세요.';
    end if;
    if not owns_pc(p_pc) then raise exception '작업장을 볼 권한이 없어요.'; end if;
    select * into v_acc from accounts where id = p_account;
    if not found then raise exception '없는 계정이에요. 새로고침한 뒤 다시 시도하세요.'; end if;
    if not can_see_account(p_account) or v_acc.team_id <> v_pc.team_id then
        raise exception '이 계정을 넣을 수 없어요. 새로고침하세요.';
    end if;
    if v_acc.withdrawn then raise exception '탈퇴한 계정은 넣을 수 없어요.'; end if;
    if v_acc.auth_blocked then raise exception '인증불가 계정은 넣을 수 없어요.'; end if;
    if v_acc.delete_requested_at is not null then raise exception '삭제 요청 중인 계정은 넣을 수 없어요.'; end if;
    select pc_id, slot into v_where from assignments where account_id = p_account;
    if found then
        raise exception '이 계정은 이미 %에 들어 있어요.', _pc_label(v_where.pc_id, v_where.slot);
    end if;
    perform _check_owner_rule(p_account, p_pc);
    begin
        insert into assignments (pc_id, slot, account_id) values (p_pc, p_slot, p_account);
    exception when unique_violation then
        raise exception '그 자리에 이미 다른 계정이 들어갔어요. 새로고침한 뒤 다시 시도하세요.';
    end;
    perform _log('배정', _pc_label(p_pc, p_slot) || ' ← ' || _acc_label(p_account), v_pc.team_id);
end $$;

create or replace function public.unassign_slot(p_pc bigint, p_slot integer) returns void
language plpgsql security definer set search_path = public as $$
declare v_acc bigint;
begin
    if not owns_pc(p_pc) then raise exception '작업장을 볼 권한이 없어요.'; end if;
    select account_id into v_acc from assignments where pc_id = p_pc and slot = p_slot;
    if v_acc is not null and not can_see_account(v_acc) then
        raise exception '이 계정은 뺄 수 없어요. 새로고침하세요.';
    end if;
    delete from assignments where pc_id = p_pc and slot = p_slot returning account_id into v_acc;
    if v_acc is not null then
        perform _log('빼기', _pc_label(p_pc, p_slot) || ' → ' || _acc_label(v_acc), (select team_id from pcs where id = p_pc));
    end if;
end $$;

create or replace function public.move_account(p_account bigint, p_pc bigint, p_slot integer) returns void
language plpgsql security definer set search_path = public as $$
declare
    v_src record;
    v_pc  pcs%rowtype;
begin
    select pc_id, slot into v_src from assignments where account_id = p_account;
    if not found then raise exception '이 계정은 어느 자리에도 없어요.'; end if;
    if not (owns_pc(v_src.pc_id) and owns_pc(p_pc)) then raise exception '작업장을 볼 권한이 없어요.'; end if;
    if not can_see_account(p_account) then raise exception '이 계정은 옮길 수 없어요. 새로고침하세요.'; end if;
    select * into v_pc from pcs where id = p_pc;
    if not found or p_slot < 1 or p_slot > v_pc.slot_count then raise exception '없는 자리예요.'; end if;
    if v_pc.team_id <> (select team_id from accounts where id = p_account) then
        raise exception '다른 팀 컴퓨터로는 옮길 수 없어요.';
    end if;
    perform _check_owner_rule(p_account, p_pc);
    begin
        update assignments set pc_id = p_pc, slot = p_slot, assigned_at = now() where account_id = p_account;
    exception when unique_violation then
        raise exception '옮길 자리에 이미 계정이 있어요. 새로고침한 뒤 다시 시도하세요.';
    end;
    perform _log('옮기기', _acc_label(p_account) || ': ' || _pc_label(v_src.pc_id, v_src.slot) || ' → ' || _pc_label(p_pc, p_slot),
                 v_pc.team_id);
end $$;

-- ============================================================ 근무자 관리
-- 총관리자: 누구든(총관리자 자신 제외) 역할, 팀, 권한을 바꿀 수 있다.
-- 관리자: 맡은 팀의 근무자만. 자기가 가진 권한까지만 켜고 끌 수 있고,
--         가입 승인과 팀 바꾸기는 '팀 배정' 권한이 있을 때 맡은 팀으로만.
create or replace function public.save_profile(p jsonb) returns void
language plpgsql security definer set search_path = public as $$
declare
    v_id    uuid := (p ->> 'id')::uuid;
    v_role  text := p ->> 'role';
    v_me    profiles%rowtype;
    v_cur   profiles%rowtype;
    v_teams bigint[];
    v_old   bigint[];
    v_super boolean;
begin
    select * into v_me from profiles where id = auth.uid();
    if not found or v_me.role not in ('super', 'admin') then raise exception '관리자만 할 수 있어요.'; end if;
    v_super := v_me.role = 'super';
    select * into v_cur from profiles where id = v_id for update;
    if not found then raise exception '없는 사용자예요. 새로고침하세요.'; end if;
    if v_id = auth.uid() then raise exception '자기 자신의 역할과 권한은 바꿀 수 없어요.'; end if;
    if v_cur.role = 'super' then raise exception '총관리자는 바꿀 수 없어요.'; end if;
    if v_cur.role = 'agent' then raise exception 'PC 실행기 계정은 여기서 바꿀 수 없어요.'; end if;
    if v_role is null or v_role not in ('admin', 'worker', 'pending') then raise exception '알 수 없는 역할이에요.'; end if;

    select coalesce(array_agg(distinct x::bigint order by x::bigint), '{}') into v_teams
      from jsonb_array_elements_text(coalesce(p -> 'teams', '[]'::jsonb)) x;
    select coalesce(array_agg(team_id order by team_id), '{}') into v_old from team_members where user_id = v_id;
    if v_role = 'pending' then v_teams := '{}'; end if;
    if v_role = 'worker' and cardinality(v_teams) <> 1 then raise exception '근무자는 팀을 하나 정해야 해요.'; end if;
    if v_role = 'admin' and cardinality(v_teams) = 0 then raise exception '관리자가 맡을 팀을 하나 이상 정하세요.'; end if;
    if exists (select 1 from unnest(v_teams) t where not exists (select 1 from teams where id = t)) then
        raise exception '없는 팀이에요. 새로고침하세요.';
    end if;

    if not v_super then
        if v_cur.role = 'admin' or v_role = 'admin' then
            raise exception '관리자 지정은 총관리자만 할 수 있어요.';
        end if;
        if v_cur.role = 'pending' then
            if not has_perm('assign_team') then raise exception '가입 승인은 팀 배정 권한이 있어야 해요.'; end if;
        elsif cardinality(v_old) = 0 or exists (select 1 from unnest(v_old) t where not is_team_admin(t)) then
            raise exception '맡은 팀의 근무자만 바꿀 수 있어요.';
        end if;
        if v_teams is distinct from v_old then
            if not has_perm('assign_team') then raise exception '팀 배정 권한이 없어요.'; end if;
            if exists (select 1 from unnest(v_teams) t where not is_team_admin(t)) then
                raise exception '맡은 팀에만 넣을 수 있어요.';
            end if;
        end if;
    end if;

    update profiles set
        display_name = coalesce(nullif(trim(p ->> 'display_name'), ''), display_name),
        role = v_role,
        can_add_account = case when v_super or has_perm('add_account')
            then coalesce((p ->> 'can_add_account')::boolean, false) else v_cur.can_add_account end,
        can_edit_account = case when v_super or has_perm('edit_account')
            then coalesce((p ->> 'can_edit_account')::boolean, false) else v_cur.can_edit_account end,
        can_delete_account = case when v_super or has_perm('delete_account')
            then coalesce((p ->> 'can_delete_account')::boolean, false) else v_cur.can_delete_account end,
        can_edit_pc = case when v_super or has_perm('edit_pc')
            then coalesce((p ->> 'can_edit_pc')::boolean, false) else v_cur.can_edit_pc end,
        can_view_workplace = case when v_super or has_perm('view_workplace')
            then coalesce((p ->> 'can_view_workplace')::boolean, true) else v_cur.can_view_workplace end,
        can_view_accounts = case when v_super or has_perm('view_accounts')
            then coalesce((p ->> 'can_view_accounts')::boolean, true) else v_cur.can_view_accounts end,
        can_control_pc = case when v_super or has_perm('control_pc')
            then coalesce((p ->> 'can_control_pc')::boolean, false) else v_cur.can_control_pc end,
        can_add_pc = case when v_super or has_perm('add_pc')
            then coalesce((p ->> 'can_add_pc')::boolean, false) else v_cur.can_add_pc end,
        can_delete_pc = case when v_super or has_perm('delete_pc')
            then coalesce((p ->> 'can_delete_pc')::boolean, false) else v_cur.can_delete_pc end,
        can_assign_team = case when v_super
            then v_role = 'admin' and coalesce((p ->> 'can_assign_team')::boolean, false) else v_cur.can_assign_team end
    where id = v_id;

    -- 팀 바꾸기: 빠진 팀의 열쇠도 회수
    delete from team_members where user_id = v_id and not (team_id = any (v_teams));
    insert into team_members (team_id, user_id) select t, v_id from unnest(v_teams) t on conflict do nothing;
    delete from team_keys where user_id = v_id and not (team_id = any (v_teams));

    perform _log('근무자 설정', format('%s: %s (%s)', coalesce(nullif(trim(p ->> 'display_name'), ''), v_cur.display_name),
        v_role, coalesce((select string_agg(name, ', ' order by id) from teams where id = any (v_teams)), '팀 없음')),
        case when cardinality(v_teams) = 1 then v_teams[1] end);
end $$;

-- ============================================================ 팀 관리 (총관리자)
-- p_check: 새 팀 열쇠로 만든 확인값, p_box: 새 팀 열쇠를 총관리자의 팀 암호로 잠근 것
create or replace function public.create_team(p_name text, p_check text, p_box text) returns bigint
language plpgsql security definer set search_path = public as $$
declare v_id bigint;
begin
    if not is_super() then raise exception '팀은 총관리자만 만들 수 있어요.'; end if;
    if trim(coalesce(p_name, '')) = '' then raise exception '팀 이름을 입력하세요.'; end if;
    if exists (select 1 from teams where name = trim(p_name)) then raise exception '같은 이름의 팀이 이미 있어요.'; end if;
    insert into teams (name, key_check) values (trim(p_name), p_check) returning id into v_id;
    insert into team_master (team_id, box) values (v_id, p_box);
    perform _log('팀 추가', trim(p_name));
    return v_id;
end $$;

create or replace function public.rename_team(p_id bigint, p_name text) returns void
language plpgsql security definer set search_path = public as $$
declare v_old text;
begin
    if not is_super() then raise exception '총관리자만 할 수 있어요.'; end if;
    if trim(coalesce(p_name, '')) = '' then raise exception '팀 이름을 입력하세요.'; end if;
    select name into v_old from teams where id = p_id;
    if not found then raise exception '없는 팀이에요. 새로고침하세요.'; end if;
    if exists (select 1 from teams where name = trim(p_name) and id <> p_id) then raise exception '같은 이름의 팀이 이미 있어요.'; end if;
    update teams set name = trim(p_name) where id = p_id;
    perform _log('팀 이름 변경', v_old || ' → ' || trim(p_name));
end $$;

create or replace function public.delete_team(p_id bigint) returns void
language plpgsql security definer set search_path = public as $$
declare v_name text;
begin
    if not is_super() then raise exception '총관리자만 할 수 있어요.'; end if;
    select name into v_name from teams where id = p_id;
    if not found then raise exception '없는 팀이에요. 새로고침하세요.'; end if;
    if exists (select 1 from pcs where team_id = p_id) or exists (select 1 from accounts where team_id = p_id) then
        raise exception '팀에 컴퓨터나 계정이 남아 있어요. 먼저 비운 뒤 삭제하세요.';
    end if;
    if (select count(*) from teams) <= 1 then raise exception '팀이 하나는 있어야 해요.'; end if;
    -- 이 팀에만 속한 근무자는 승인 대기로 돌린다
    update profiles set role = 'pending'
     where role in ('worker', 'admin') and id in (select user_id from team_members where team_id = p_id)
       and not exists (select 1 from team_members m where m.user_id = profiles.id and m.team_id <> p_id);
    delete from teams where id = p_id;
    perform _log('팀 삭제', v_name);
end $$;

-- 총관리자 프로그램이 처음 팀 열쇠를 정하거나(확인값이 빈 팀) 팀 암호로 잠근 사본을 저장할 때
create or replace function public.set_team_secret(p_id bigint, p_check text, p_box text) returns void
language plpgsql security definer set search_path = public as $$
begin
    if not is_super() then raise exception '총관리자만 할 수 있어요.'; end if;
    update teams set key_check = p_check where id = p_id and key_check = '';
    insert into team_master (team_id, box) values (p_id, p_box) on conflict (team_id) do nothing;
end $$;

-- ============================================================ 개인 열쇠와 팀 열쇠 넘겨주기
create or replace function public.register_key(p_public text, p_salt text, p_box text) returns void
language plpgsql security definer set search_path = public as $$
declare v_old text;
begin
    if auth.uid() is null or not exists (select 1 from profiles where id = auth.uid()) then
        raise exception '로그인이 필요해요.';
    end if;
    select public_key into v_old from user_keys where user_id = auth.uid();
    if v_old is distinct from p_public then
        insert into user_keys (user_id, public_key) values (auth.uid(), p_public)
        on conflict (user_id) do update set public_key = excluded.public_key, updated_at = now();
        delete from team_keys where user_id = auth.uid();  -- 예전 열쇠로 잠근 팀 열쇠는 못 쓰니 다시 받는다
    end if;
    if coalesce(p_box, '') <> '' then
        insert into user_secrets (user_id, salt, box) values (auth.uid(), p_salt, p_box)
        on conflict (user_id) do update set salt = excluded.salt, box = excluded.box;
    elsif v_old is distinct from p_public then
        delete from user_secrets where user_id = auth.uid();
    end if;
end $$;

create or replace function public.grant_team_key(p_team bigint, p_user uuid, p_public text, p_sealed text) returns void
language plpgsql security definer set search_path = public as $$
begin
    if not is_team_admin(p_team) then raise exception '이 팀 관리자만 할 수 있어요.'; end if;
    if not exists (select 1 from team_members where team_id = p_team and user_id = p_user) then
        raise exception '이 팀에 없는 사람이에요.';
    end if;
    if not exists (select 1 from user_keys where user_id = p_user and public_key = p_public) then
        raise exception '개인 열쇠가 바뀌었어요. 새로고침하세요.';
    end if;
    insert into team_keys (team_id, user_id, public_key, sealed) values (p_team, p_user, p_public, p_sealed)
    on conflict (team_id, user_id) do update set public_key = excluded.public_key, sealed = excluded.sealed;
end $$;

-- ============================================================ 팀 암호(총관리자) 설정
create or replace function public.set_team_key(p_salt text, p_check text) returns void
language plpgsql security definer set search_path = public as $$
begin
    if not is_super() then raise exception '총관리자만 할 수 있어요.'; end if;
    if exists (select 1 from app_settings where key = 'key_salt') then
        raise exception '팀 암호가 이미 설정돼 있어요.';
    end if;
    insert into app_settings (key, value) values ('key_salt', p_salt), ('key_check', p_check);
    perform _log('팀 암호 설정', '');
end $$;

-- ============================================================ 게임 종류 (팀 관리자)
-- teams.games = ["메랜","플래닛", ...]  (계정 표의 닉/레벨직업/정지 열이 이 순서대로 생김)
drop function if exists public.set_games(jsonb);
create or replace function public.set_games(p_team bigint, p jsonb) returns void
language plpgsql security definer set search_path = public as $$
begin
    if not is_team_admin(p_team) then raise exception '관리자만 할 수 있어요.'; end if;
    if jsonb_typeof(p) <> 'array' or jsonb_array_length(p) = 0 then raise exception '게임이 하나 이상 있어야 해요.'; end if;
    update teams set games = p where id = p_team;
    perform _log('게임 종류 변경', (select string_agg(x, ', ') from jsonb_array_elements_text(p) x), p_team);
end $$;

-- ============================================================ 변경 감지 (자동 새로고침용)
drop function if exists public.last_change();
create or replace function public.last_change(p_team bigint) returns bigint
language sql stable security definer set search_path = public as $$
    select case when in_team(p_team) then
        greatest(coalesce((select max(id) from audit_log where team_id = p_team), 0),
                 coalesce((select max(id) from audit_log where team_id is null), 0))
    else 0 end
$$;

-- ============================================================ 엑셀/로컬 데이터 한꺼번에 올리기 (총관리자, 팀 하나)
-- p = {"accounts":[{..., "characters":[...]}], "pcs":[{...}], "links":[{"pc_no":1,"slot":1,"acc":0}]}
drop function if exists public.import_data(jsonb);
create or replace function public.import_data(p_team bigint, p jsonb) returns integer
language plpgsql security definer set search_path = public as $$
declare
    a      jsonb;
    pc     jsonb;
    l      jsonb;
    c      jsonb;
    k      integer;
    v_id   bigint;
    ids    bigint[] := '{}';
    n_link integer := 0;
begin
    if not is_super() then raise exception '총관리자만 할 수 있어요.'; end if;
    if not exists (select 1 from teams where id = p_team) then raise exception '없는 팀이에요.'; end if;
    delete from accounts where team_id = p_team;   -- 캐릭터와 배정도 같이 지워진다
    delete from pcs where team_id = p_team;

    for a in select * from jsonb_array_elements(p -> 'accounts') loop
        insert into accounts (team_id, owner, contact, provider, login_id, login_key, password, tag,
                              mr_banned, mr_until, pl_banned, pl_until, withdrawn, note,
                              auth_blocked, other_bans)
        values (p_team, coalesce(a ->> 'owner', ''), coalesce(a ->> 'contact', ''), coalesce(a ->> 'provider', ''),
                trim(a ->> 'login_id'), lower(trim(a ->> 'login_id')), coalesce(a ->> 'password', ''),
                coalesce(a ->> 'tag', ''), coalesce((a ->> 'mr_banned')::boolean, false), coalesce(a ->> 'mr_until', ''),
                coalesce((a ->> 'pl_banned')::boolean, false), coalesce(a ->> 'pl_until', ''),
                coalesce((a ->> 'withdrawn')::boolean, false), coalesce(a ->> 'note', ''),
                coalesce((a ->> 'auth_blocked')::boolean, false), coalesce(a -> 'other_bans', '{}'::jsonb))
        returning id into v_id;
        ids := ids || v_id;
        k := 0;
        for c in select * from jsonb_array_elements(coalesce(a -> 'characters', '[]'::jsonb)) loop
            insert into characters (account_id, game, nickname, level_job, sort)
            values (v_id, c ->> 'game', coalesce(c ->> 'nickname', ''), coalesce(c ->> 'level_job', ''), k);
            k := k + 1;
        end loop;
    end loop;

    for pc in select * from jsonb_array_elements(p -> 'pcs') loop
        insert into pcs (team_id, no, name, remote_t, anydesk_id, anydesk_pw, vpn, ld_cloud, slot_count, note)
        values (p_team, (pc ->> 'no')::integer, coalesce(pc ->> 'name', ''), coalesce(pc ->> 'remote_t', ''),
                coalesce(pc ->> 'anydesk_id', ''), coalesce(pc ->> 'anydesk_pw', ''), coalesce(pc ->> 'vpn', ''),
                '', coalesce((pc ->> 'slot_count')::integer, 2), coalesce(pc ->> 'note', ''));
    end loop;

    for l in select * from jsonb_array_elements(p -> 'links') loop
        insert into assignments (pc_id, slot, account_id)
        select id, (l ->> 'slot')::integer, ids[(l ->> 'acc')::integer + 1]
        from pcs where team_id = p_team and no = (l ->> 'pc_no')::integer
        on conflict do nothing;
        get diagnostics k = row_count;
        n_link := n_link + k;
    end loop;

    perform _log('데이터 올리기', format('계정 %s개, 컴퓨터 %s대, 배정 %s건',
        jsonb_array_length(p -> 'accounts'), jsonb_array_length(p -> 'pcs'), n_link), p_team);
    return n_link;
end $$;


-- ============================================================ PC 실행기 (LD CLOUD 실행기 원격 조종)
-- 각 PC의 실행기는 스스로 가입(역할 agent)하고, 관리자가 작업장의 컴퓨터와 연결해 준다.
-- 명령은 pc_commands에 쌓이고 실행기가 가져가서 실행한 뒤 결과를 적는다.
-- 자리 계정의 아이디/비번은 그 PC 실행기만 열 수 있게 잠가서 pc_creds에 둔다 (1자리 = A, 2자리 = B).
create table if not exists public.agents (
    user_id     uuid primary key references public.profiles(id) on delete cascade,
    pc_id       bigint unique references public.pcs(id) on delete set null,
    machine     text not null default '',      -- Windows 컴퓨터 이름
    public_key  text not null default '',      -- 계정 비번을 잠글 때 쓰는 열쇠 (P-256)
    version     text not null default '',
    last_seen   timestamptz,
    state       jsonb not null default '{}'::jsonb,   -- {"busy":true,"job":"A 로그인","last":"..."}
    devices     jsonb not null default '[]'::jsonb,   -- LD CLOUD 기기 목록 ["이름 #ID", ...]
    created_at  timestamptz not null default now()
);

-- 실행기 설정 (열 클라우드, 재시작 옵션, 단축키 등). 작업장 프로그램에서만 바꾼다
alter table public.pcs add column if not exists agent_settings jsonb not null default '{}'::jsonb;

create table if not exists public.pc_creds (
    pc_id        bigint not null references public.pcs(id) on delete cascade,
    slot         integer not null,
    sealed       text not null,
    fingerprint  text not null,
    updated_at   timestamptz not null default now(),
    primary key (pc_id, slot)
);

create table if not exists public.pc_commands (
    id           bigint generated always as identity primary key,
    pc_id        bigint not null references public.pcs(id) on delete cascade,
    kind         text not null check (kind in ('start', 'restart', 'close', 'login_a', 'login_b', 'stop',
                                        'amp_run', 'amp_stop', 'map_run', 'map_stop', 'amp_folder', 'map_folder',
                                        'amp_clear', 'map_clear', 'reload_devices', 'find_ld', 'restart_agent')),
    status       text not null default 'queued' check (status in ('queued', 'running', 'done', 'failed', 'cancelled')),
    result       text not null default '',
    log          text not null default '',
    created_by   uuid,
    created_name text not null default '',
    created_at   timestamptz not null default now(),
    started_at   timestamptz,
    finished_at  timestamptz
);
create index if not exists pc_commands_pc_idx on public.pc_commands(pc_id, id);
-- 명령 종류가 늘어나면 제한을 다시 건다
alter table public.pc_commands drop constraint if exists pc_commands_kind_check;
alter table public.pc_commands add constraint pc_commands_kind_check check (kind in ('start', 'restart', 'close', 'login_a', 'login_b', 'stop',
                                        'amp_run', 'amp_stop', 'map_run', 'map_stop', 'amp_folder', 'map_folder',
                                        'amp_clear', 'map_clear', 'reload_devices', 'find_ld', 'restart_agent'));

-- LD 클라우드 표기 '이름 #ID' 나누기
create or replace function public._cloud_id(c text) returns text
language sql immutable as $$
    select nullif(trim(split_part(coalesce(c, ''), '#', 2)), '')
$$;

create or replace function public._cloud_name(c text) returns text
language sql immutable as $$
    select trim(split_part(coalesce(c, ''), ' #', 1))
$$;

-- 이 실행기(로그인한 agent)가 연결된 컴퓨터
create or replace function public._my_agent_pc() returns bigint
language sql stable security definer set search_path = public as $$
    select pc_id from agents where user_id = auth.uid()
$$;

create or replace function public._pc_team(p bigint) returns bigint
language sql stable security definer set search_path = public as $$
    select team_id from pcs where id = p
$$;

-- 이 컴퓨터를 조종할 수 있는지: 같은 팀 + PC 조종 권한
create or replace function public._can_control(p bigint) returns boolean
language sql stable security definer set search_path = public as $$
    select is_super() or (in_team(_pc_team(p)) and has_perm('control_pc'))
$$;

alter table public.agents       enable row level security;
alter table public.pc_creds     enable row level security;
alter table public.pc_commands  enable row level security;

drop policy if exists agents_read on public.agents;
create policy agents_read on public.agents for select to authenticated
    using (user_id = auth.uid()
           or (pc_id is null and is_admin())
           or (pc_id is not null and (_pc_visible(_pc_team(pc_id)) or _can_control(pc_id))));

drop policy if exists pc_creds_read on public.pc_creds;
create policy pc_creds_read on public.pc_creds for select to authenticated
    using (pc_id = _my_agent_pc() or _can_control(pc_id) or is_team_admin(_pc_team(pc_id)));

drop policy if exists pc_commands_read on public.pc_commands;
create policy pc_commands_read on public.pc_commands for select to authenticated
    using (pc_id = _my_agent_pc() or _pc_visible(_pc_team(pc_id)) or _can_control(pc_id));

-- 실행기: 처음 켤 때와 열쇠가 바뀔 때 등록
create or replace function public.agent_register(p_machine text, p_public text, p_version text) returns void
language plpgsql security definer set search_path = public as $$
declare v_old agents%rowtype;
begin
    if my_role() is distinct from 'agent' then raise exception 'PC 실행기 계정만 할 수 있어요.'; end if;
    select * into v_old from agents where user_id = auth.uid();
    insert into agents (user_id, machine, public_key, version, last_seen)
    values (auth.uid(), coalesce(p_machine, ''), coalesce(p_public, ''), coalesce(p_version, ''), now())
    on conflict (user_id) do update set machine = excluded.machine, public_key = excluded.public_key,
        version = excluded.version, last_seen = now();
    -- 열쇠가 바뀌면 예전 열쇠로 잠근 계정은 못 여니 지운다 (작업장 프로그램이 다시 잠가서 올림)
    if v_old.pc_id is not null and v_old.public_key is distinct from p_public then
        delete from pc_creds where pc_id = v_old.pc_id;
    end if;
end $$;

-- 실행기: 주기적으로 상태를 알리고, 설정과 다음 명령을 받는다
-- 돌려주는 값: {"pc_id":..,"pc_no":..,"pc_name":..,"settings":{..},"creds":"지문들","command":{"id":..,"kind":".."} 또는 null}
create or replace function public.agent_sync(p_state jsonb, p_devices jsonb) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
    v_ag      agents%rowtype;
    v_pc      pcs%rowtype;
    v_cmd     pc_commands%rowtype;
    v_cloud   text;
    v_cid     text;
    v_cands   bigint[];
    v_changed bigint;
begin
    if my_role() is distinct from 'agent' then raise exception 'PC 실행기 계정만 할 수 있어요.'; end if;
    update agents set last_seen = now(), state = coalesce(p_state, state),
        devices = case when p_devices is null or jsonb_typeof(p_devices) <> 'array' or jsonb_array_length(p_devices) = 0
                       then devices else p_devices end
    where user_id = auth.uid() returning * into v_ag;
    if not found then raise exception '먼저 등록해야 해요.'; end if;
    v_cloud := v_ag.state -> 'cfg' ->> 'cloud';
    v_cid := _cloud_id(v_cloud);
    -- 자동 연결: 작업장 PC 조종에서 이 클라우드를 정해 둔 컴퓨터가 딱 하나 있고, 거기에 다른 실행기가 없고,
    -- 같은 클라우드를 여는 다른 연결 대기 실행기도 없으면 그 컴퓨터에 연결한다
    if v_ag.pc_id is null and v_cid is not null then
        select array_agg(id) into v_cands from pcs where _cloud_id(agent_settings ->> 'cloud') = v_cid;
        if cardinality(v_cands) = 1
           and not exists (select 1 from agents where pc_id = v_cands[1])
           and not exists (select 1 from agents a where a.pc_id is null and a.user_id <> v_ag.user_id
                           and a.last_seen > now() - interval '10 minutes'
                           and _cloud_id(a.state -> 'cfg' ->> 'cloud') = v_cid) then
            update agents set pc_id = v_cands[1] where user_id = v_ag.user_id;
            v_ag.pc_id := v_cands[1];
            delete from pc_creds where pc_id = v_cands[1];
            perform _log('실행기 자동 연결', v_ag.machine || ' → ' || _pc_no_label(v_cands[1]) || ' (' || _cloud_name(v_cloud) || ')',
                         _pc_team(v_cands[1]));
        end if;
    end if;
    if v_ag.pc_id is null then return jsonb_build_object('pc_id', null); end if;
    -- 작업장 LD클라우드 칸 = 이 실행기가 실제로 여는 클라우드 (바뀌면 기록을 남겨 다른 화면도 새로고침되게)
    if _cloud_name(v_cloud) <> '' then
        update pcs set ld_cloud = _cloud_name(v_cloud), updated_at = now()
         where id = v_ag.pc_id and ld_cloud is distinct from _cloud_name(v_cloud)
        returning id into v_changed;
        if v_changed is not null then
            perform _log('실행기 클라우드', _pc_no_label(v_ag.pc_id) || ': ' || _cloud_name(v_cloud), _pc_team(v_ag.pc_id));
        end if;
    end if;
    select * into v_pc from pcs where id = v_ag.pc_id;
    -- 대기 중인 명령 하나를 가져가며 '실행 중'으로 (중지 명령이 있으면 그것 먼저)
    select * into v_cmd from pc_commands
     where pc_id = v_ag.pc_id and status = 'queued'
     order by (kind = 'stop') desc, id limit 1 for update skip locked;
    if found then
        update pc_commands set status = 'running', started_at = now() where id = v_cmd.id;
    end if;
    return jsonb_build_object(
        'pc_id', v_pc.id, 'pc_no', v_pc.no, 'pc_name', v_pc.name, 'ld_cloud', v_pc.ld_cloud,
        'settings', v_pc.agent_settings,
        'creds', coalesce((select string_agg(slot || ':' || fingerprint, ',' order by slot) from pc_creds where pc_id = v_pc.id), ''),
        'command', case when v_cmd.id is null then null else jsonb_build_object('id', v_cmd.id, 'kind', v_cmd.kind) end);
end $$;

-- 실행기: 명령 진행 상황/결과 적기 (p_log는 덧붙일 줄)
create or replace function public.agent_report(p_id bigint, p_status text, p_result text, p_log text) returns void
language plpgsql security definer set search_path = public as $$
begin
    if my_role() is distinct from 'agent' then raise exception 'PC 실행기 계정만 할 수 있어요.'; end if;
    if p_status not in ('running', 'done', 'failed', 'cancelled') then raise exception '알 수 없는 상태예요.'; end if;
    update pc_commands set
        status = p_status,
        result = coalesce(p_result, result),
        log = right(log || coalesce(p_log, ''), 20000),
        finished_at = case when p_status in ('done', 'failed', 'cancelled') then now() else finished_at end
    where id = p_id and pc_id = _my_agent_pc();
end $$;

-- 관리자: 실행기를 작업장 컴퓨터에 연결 (p_pc = null 이면 연결 끊기)
create or replace function public.link_agent(p_agent uuid, p_pc bigint) returns void
language plpgsql security definer set search_path = public as $$
declare
    v_ag   agents%rowtype;
    v_team bigint;
begin
    select * into v_ag from agents where user_id = p_agent for update;
    if not found then raise exception '없는 실행기예요. 새로고침하세요.'; end if;
    if v_ag.pc_id is not null and not is_team_admin(_pc_team(v_ag.pc_id)) then
        raise exception '이 실행기는 다른 팀 컴퓨터에 연결돼 있어요.';
    end if;
    if p_pc is not null then
        v_team := _pc_team(p_pc);
        if v_team is null then raise exception '없는 컴퓨터예요.'; end if;
        if not is_team_admin(v_team) then raise exception '이 팀 관리자만 연결할 수 있어요.'; end if;
        update agents set pc_id = null where pc_id = p_pc and user_id <> p_agent;  -- 예전 실행기는 연결 끊음
    elsif not is_admin() then
        raise exception '관리자만 할 수 있어요.';
    end if;
    if v_ag.pc_id is not null then delete from pc_creds where pc_id = v_ag.pc_id; end if;
    if p_pc is not null then delete from pc_creds where pc_id = p_pc; end if;
    update agents set pc_id = p_pc where user_id = p_agent;
    -- 작업장 LD클라우드 칸은 실행기가 여는 클라우드만 보여준다: 떠나는 컴퓨터는 비우고, 새 컴퓨터는 그 실행기 값으로
    if v_ag.pc_id is not null and v_ag.pc_id is distinct from p_pc then
        update pcs set ld_cloud = '', updated_at = now() where id = v_ag.pc_id;
    end if;
    if p_pc is not null then
        update pcs set ld_cloud = _cloud_name(v_ag.state -> 'cfg' ->> 'cloud'), updated_at = now() where id = p_pc;
        -- 이 컴퓨터에 클라우드가 아직 안 정해져 있으면 이 실행기의 클라우드를 기억 (다음에 켜지면 자동 연결)
        if _cloud_id(v_ag.state -> 'cfg' ->> 'cloud') is not null then
            update pcs set agent_settings = coalesce(agent_settings, '{}'::jsonb)
                                           || jsonb_build_object('cloud', v_ag.state -> 'cfg' ->> 'cloud')
             where id = p_pc and coalesce(agent_settings ->> 'cloud', '') = ''
               and not exists (select 1 from pcs q where q.id <> p_pc
                               and _cloud_id(q.agent_settings ->> 'cloud') = _cloud_id(v_ag.state -> 'cfg' ->> 'cloud'));
        end if;
    end if;
    perform _log(case when p_pc is null then '실행기 연결 끊기' else '실행기 연결' end,
                 v_ag.machine || coalesce(' → ' || _pc_no_label(p_pc), ''), coalesce(v_team, _pc_team(v_ag.pc_id)));
end $$;

-- 관리자: 연결 안 된 실행기 지우기 (잘못 등록된 것)
create or replace function public.forget_agent(p_agent uuid) returns void
language plpgsql security definer set search_path = public as $$
declare v_ag agents%rowtype;
begin
    select * into v_ag from agents where user_id = p_agent;
    if not found then return; end if;
    if v_ag.pc_id is not null then raise exception '컴퓨터에 연결된 실행기는 먼저 연결을 끊으세요.'; end if;
    if not is_admin() then raise exception '관리자만 할 수 있어요.'; end if;
    delete from agents where user_id = p_agent;
end $$;

-- PC 조종: 명령 보내기
create or replace function public.send_pc_command(p_pc bigint, p_kind text) returns bigint
language plpgsql security definer set search_path = public as $$
declare v_id bigint;
begin
    if not _can_control(p_pc) then raise exception 'PC 조종 권한이 없어요.'; end if;
    if not exists (select 1 from agents where pc_id = p_pc) then raise exception '이 컴퓨터에 연결된 실행기가 없어요.'; end if;
    if p_kind = 'stop' then
        update pc_commands set status = 'cancelled', finished_at = now(), result = '중지 요청으로 취소'
         where pc_id = p_pc and status = 'queued';
    elsif exists (select 1 from pc_commands where pc_id = p_pc and status = 'queued' and kind = p_kind) then
        raise exception '같은 명령이 이미 기다리고 있어요.';
    end if;
    insert into pc_commands (pc_id, kind, created_by, created_name)
    values (p_pc, p_kind, auth.uid(), coalesce((select display_name from profiles where id = auth.uid()), ''))
    returning id into v_id;
    perform _log('PC 명령', _pc_no_label(p_pc) || ' ' || p_kind, _pc_team(p_pc));
    return v_id;
end $$;

-- PC 조종: 실행기 설정 바꾸기
create or replace function public.set_agent_settings(p_pc bigint, p jsonb) returns void
language plpgsql security definer set search_path = public as $$
begin
    if not _can_control(p_pc) then raise exception 'PC 조종 권한이 없어요.'; end if;
    if jsonb_typeof(p) <> 'object' then raise exception '설정 형식이 잘못됐어요.'; end if;
    update pcs set agent_settings = p, updated_at = now() where id = p_pc;
    perform _log('실행기 설정', _pc_no_label(p_pc), _pc_team(p_pc));
end $$;

-- 자리 계정을 그 PC 실행기 열쇠로 잠가서 올리기 (작업장 프로그램이 자동으로 함). p_sealed = '' 이면 지움
create or replace function public.set_pc_creds(p_pc bigint, p_slot integer, p_sealed text, p_fp text) returns void
language plpgsql security definer set search_path = public as $$
begin
    if not (_can_control(p_pc) or is_team_admin(_pc_team(p_pc))) then raise exception 'PC 조종 권한이 없어요.'; end if;
    if coalesce(p_sealed, '') = '' then
        delete from pc_creds where pc_id = p_pc and slot = p_slot;
    else
        insert into pc_creds (pc_id, slot, sealed, fingerprint) values (p_pc, p_slot, p_sealed, p_fp)
        on conflict (pc_id, slot) do update set sealed = excluded.sealed, fingerprint = excluded.fingerprint, updated_at = now();
    end if;
end $$;

-- 실행기: 잠긴 자리 계정 받기
create or replace function public.agent_creds() returns jsonb
language sql stable security definer set search_path = public as $$
    select coalesce(jsonb_agg(jsonb_build_object('slot', slot, 'sealed', sealed, 'fingerprint', fingerprint) order by slot), '[]'::jsonb)
      from pc_creds where pc_id = _my_agent_pc() and my_role() = 'agent'
$$;

-- 한 번만: 작업장 LD클라우드 칸을 엑셀 값 대신 실행기가 여는 클라우드로 바꾼다
do $$
begin
    if not exists (select 1 from public.app_settings where key = 'ld_cloud_from_agents') then
        update public.pcs p set ld_cloud = coalesce((select public._cloud_name(a.state -> 'cfg' ->> 'cloud')
                                                     from public.agents a where a.pc_id = p.id), '')
         where true;
        insert into public.app_settings (key, value) values ('ld_cloud_from_agents', '1');
    end if;
end $$;

-- 실행기가 명령을 바로 알 수 있게 (Supabase Realtime). 시험용 DB처럼 없으면 건너뛴다
do $$
begin
    if exists (select 1 from pg_publication where pubname = 'supabase_realtime')
       and not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime' and tablename = 'pc_commands') then
        alter publication supabase_realtime add table public.pc_commands;
    end if;
end $$;

-- ============================================================ 테이블 접근 권한
-- 프로젝트 생성 시 'Grant API access to new tables automatically'를 끈 경우에도 동작하도록 직접 지정한다.
-- 로그인한 사용자(authenticated)는 읽기만 가능(실제로 보이는 행은 위의 RLS가 결정), 로그인 안 한 사용자(anon)는 접근 불가.
grant usage on schema public to authenticated;
revoke all on public.profiles, public.teams, public.team_master, public.team_members, public.user_keys,
              public.user_secrets, public.team_keys, public.pcs, public.accounts, public.characters,
              public.assignments, public.audit_log, public.app_settings,
              public.agents, public.pc_creds, public.pc_commands from anon, authenticated;
grant select on public.profiles, public.teams, public.team_master, public.team_members, public.user_keys,
                public.user_secrets, public.team_keys, public.pcs, public.accounts, public.characters,
                public.assignments, public.audit_log, public.app_settings,
                public.agents, public.pc_creds, public.pc_commands to authenticated;

-- ============================================================ 실행 권한
revoke execute on all functions in schema public from public, anon;
grant execute on function
    public.my_role(), public.is_super(), public.is_admin(), public.is_member(), public.in_team(bigint),
    public.is_team_admin(bigint), public.has_perm(text), public._acc_visible(bigint, timestamptz),
    public.can_see_account(bigint), public._pc_visible(bigint), public.owns_pc(bigint),
    public._shares_team(uuid), public._can_see_profile(uuid),
    public.save_account(jsonb), public.delete_account(bigint), public.approve_delete(bigint), public.reject_delete(bigint),
    public.save_pc(jsonb), public.delete_pc(bigint), public.swap_pc_numbers(bigint, bigint),
    public.assign_account(bigint, integer, bigint), public.unassign_slot(bigint, integer),
    public.move_account(bigint, bigint, integer),
    public.save_profile(jsonb), public.create_team(text, text, text), public.rename_team(bigint, text),
    public.delete_team(bigint), public.set_team_secret(bigint, text, text),
    public.register_key(text, text, text), public.grant_team_key(bigint, uuid, text, text),
    public.set_team_key(text, text), public.set_games(bigint, jsonb),
    public.last_change(bigint), public.import_data(bigint, jsonb),
    public._my_agent_pc(), public._pc_team(bigint), public._can_control(bigint), public._cloud_id(text), public._cloud_name(text),
    public.agent_register(text, text, text), public.agent_sync(jsonb, jsonb), public.agent_report(bigint, text, text, text),
    public.link_agent(uuid, bigint), public.forget_agent(uuid), public.send_pc_command(bigint, text),
    public.set_agent_settings(bigint, jsonb), public.set_pc_creds(bigint, integer, text, text), public.agent_creds()
to authenticated;
