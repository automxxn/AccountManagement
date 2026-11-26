-- AccountManagement 클라우드 DB 구조와 권한 규칙
-- Supabase 대시보드 → SQL Editor 에 이 파일 전체를 붙여넣고 Run 하세요. (여러 번 실행해도 안전합니다)
--
-- 원칙
--  * 테이블은 읽기만 RLS로 허용하고, 쓰기는 전부 아래 함수(RPC)로만 한다. 함수 안에서 권한을 검사한다.
--  * 첫 번째로 가입한 사용자가 관리자가 되고, 이후 가입자는 '대기' 상태로 관리자 승인을 기다린다.
--  * 근무자는 자기 담당 컴퓨터, 자기 담당 계정, 자기 컴퓨터에 들어간 계정만 본다.

-- ============================================================ 테이블
create table if not exists public.profiles (
    id                  uuid primary key references auth.users(id) on delete cascade,
    login               text not null default '',
    display_name        text not null default '',
    role                text not null default 'pending' check (role in ('admin', 'worker', 'pending')),
    can_add_account     boolean not null default false,
    can_edit_account    boolean not null default false,
    can_delete_account  boolean not null default false,
    can_edit_pc         boolean not null default false,
    created_at          timestamptz not null default now()
);

create table if not exists public.pcs (
    id          bigint generated always as identity primary key,
    no          integer not null unique,
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
    updated_at  timestamptz not null default now(),
    unique (provider, login_key)
);

create table if not exists public.characters (
    id          bigint generated always as identity primary key,
    account_id  bigint not null references public.accounts(id) on delete cascade,
    game        text not null check (game in ('메랜', '플래닛')),
    nickname    text not null default '',
    level_job   text not null default '',
    sort        integer not null default 0
);
create index if not exists characters_account_idx on public.characters(account_id);

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

-- ============================================================ 가입 시 프로필 자동 생성
create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
    insert into public.profiles (id, login, display_name, role,
                                 can_add_account, can_edit_account, can_delete_account, can_edit_pc)
    values (new.id,
            coalesce(new.email, ''),
            coalesce(nullif(new.raw_user_meta_data ->> 'display_name', ''), split_part(coalesce(new.email, ''), '@', 1)),
            case when exists (select 1 from public.profiles where role = 'admin') then 'pending' else 'admin' end,
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

create or replace function public.is_admin() returns boolean
language sql stable security definer set search_path = public as $$
    select coalesce(my_role() = 'admin', false)
$$;

create or replace function public.is_member() returns boolean
language sql stable security definer set search_path = public as $$
    select coalesce(my_role() in ('admin', 'worker'), false)
$$;

create or replace function public.has_perm(perm_name text) returns boolean
language sql stable security definer set search_path = public as $$
    select coalesce((
        select case
            when pr.role = 'admin' then true
            when pr.role <> 'worker' then false
            when perm_name = 'add_account' then pr.can_add_account
            when perm_name = 'edit_account' then pr.can_edit_account
            when perm_name = 'delete_account' then pr.can_delete_account
            when perm_name = 'edit_pc' then pr.can_edit_pc
            else false end
        from profiles pr where pr.id = auth.uid()), false)
$$;

-- 근무자가 볼 수 있는 계정: 자기 담당 계정 + 자기 담당 컴퓨터에 들어간 계정
create or replace function public.can_see_account(a_id bigint) returns boolean
language sql stable security definer set search_path = public as $$
    select is_admin()
        or (is_member() and (
            exists (select 1 from accounts a where a.id = a_id and a.worker_id = auth.uid())
            or exists (select 1 from assignments s join pcs p on p.id = s.pc_id
                       where s.account_id = a_id and p.worker_id = auth.uid())))
$$;

create or replace function public.owns_pc(p_id bigint) returns boolean
language sql stable security definer set search_path = public as $$
    select is_admin() or (is_member() and exists (select 1 from pcs where id = p_id and worker_id = auth.uid()))
$$;

-- ============================================================ 읽기 권한 (RLS)
alter table public.profiles     enable row level security;
alter table public.pcs          enable row level security;
alter table public.accounts     enable row level security;
alter table public.characters   enable row level security;
alter table public.assignments  enable row level security;
alter table public.audit_log    enable row level security;
alter table public.app_settings enable row level security;

drop policy if exists profiles_read on public.profiles;
create policy profiles_read on public.profiles for select to authenticated
    using (id = auth.uid() or is_admin());

drop policy if exists pcs_read on public.pcs;
create policy pcs_read on public.pcs for select to authenticated
    using (is_admin() or (is_member() and worker_id = auth.uid()));

drop policy if exists accounts_read on public.accounts;
create policy accounts_read on public.accounts for select to authenticated
    using (can_see_account(id));

drop policy if exists characters_read on public.characters;
create policy characters_read on public.characters for select to authenticated
    using (can_see_account(account_id));

drop policy if exists assignments_read on public.assignments;
create policy assignments_read on public.assignments for select to authenticated
    using (owns_pc(pc_id));

drop policy if exists audit_read on public.audit_log;
create policy audit_read on public.audit_log for select to authenticated
    using (is_admin() or (is_member() and actor_id = auth.uid()));

drop policy if exists settings_read on public.app_settings;
create policy settings_read on public.app_settings for select to authenticated
    using (is_member() or key in ('key_salt', 'key_check'));

-- 쓰기 정책은 일부러 만들지 않는다 → 테이블 직접 수정 불가, 아래 함수로만 가능

-- ============================================================ 내부 도우미
create or replace function public._log(p_action text, p_detail text) returns void
language sql security definer set search_path = public as $$
    insert into audit_log (actor_id, actor, action, detail)
    select auth.uid(), coalesce((select display_name from profiles where id = auth.uid()), '?'), p_action, p_detail
$$;

create or replace function public._acc_label(a_id bigint) returns text
language sql stable security definer set search_path = public as $$
    select coalesce((select format('[%s] %s (%s)', provider, login_id, owner) from accounts where id = a_id), '계정#' || a_id)
$$;

create or replace function public._pc_label(p_id bigint, p_slot integer) returns text
language sql stable security definer set search_path = public as $$
    select coalesce((select format('%s번 컴퓨터 %s자리', no, p_slot) from pcs where id = p_id), '컴퓨터#' || p_id)
$$;

-- ============================================================ 계정
create or replace function public.save_account(p jsonb) returns bigint
language plpgsql security definer set search_path = public as $$
declare
    v_id      bigint := nullif(p ->> 'id', '')::bigint;
    v_key     text := lower(trim(coalesce(p ->> 'login_id', '')));
    v_prov    text := trim(coalesce(p ->> 'provider', ''));
    v_worker  uuid;
    v_cur     accounts%rowtype;
    c         jsonb;
    i         integer := 0;
begin
    if not is_member() then raise exception '권한이 없어요. 관리자 승인을 기다려 주세요.'; end if;
    if v_key = '' then raise exception '아이디를 입력하세요.'; end if;

    if v_id is null then
        if not has_perm('add_account') then raise exception '계정 추가 권한이 없어요.'; end if;
        v_worker := case when is_admin() then nullif(p ->> 'worker_id', '')::uuid else auth.uid() end;
    else
        select * into v_cur from accounts where id = v_id for update;
        if not found then raise exception '없는 계정이에요. 새로고침한 뒤 다시 시도하세요.'; end if;
        if not (is_admin() or (can_see_account(v_id) and has_perm('edit_account'))) then
            raise exception '이 계정을 수정할 권한이 없어요.';
        end if;
        if v_cur.version <> coalesce((p ->> 'version')::integer, -1) then
            raise exception '다른 사람이 먼저 이 계정을 수정했어요. 새로고침한 뒤 다시 수정하세요.';
        end if;
        v_worker := case when is_admin() then nullif(p ->> 'worker_id', '')::uuid else v_cur.worker_id end;
    end if;

    if exists (select 1 from accounts where provider = v_prov and login_key = v_key and id is distinct from v_id) then
        raise exception '같은 아이디가 이미 등록돼 있어요: [%] %', v_prov, trim(p ->> 'login_id');
    end if;

    if v_id is null then
        insert into accounts (owner, contact, provider, login_id, login_key, password, tag,
                              mr_banned, mr_until, pl_banned, pl_until, withdrawn, note, worker_id)
        values (trim(coalesce(p ->> 'owner', '')), trim(coalesce(p ->> 'contact', '')), v_prov,
                trim(p ->> 'login_id'), v_key, coalesce(p ->> 'password', ''), trim(coalesce(p ->> 'tag', '')),
                coalesce((p ->> 'mr_banned')::boolean, false), coalesce(p ->> 'mr_until', ''),
                coalesce((p ->> 'pl_banned')::boolean, false), coalesce(p ->> 'pl_until', ''),
                coalesce((p ->> 'withdrawn')::boolean, false), coalesce(p ->> 'note', ''), v_worker)
        returning id into v_id;
        perform _log('계정 추가', _acc_label(v_id));
    else
        update accounts set
            owner = trim(coalesce(p ->> 'owner', '')), contact = trim(coalesce(p ->> 'contact', '')),
            provider = v_prov, login_id = trim(p ->> 'login_id'), login_key = v_key,
            password = coalesce(p ->> 'password', ''), tag = trim(coalesce(p ->> 'tag', '')),
            mr_banned = coalesce((p ->> 'mr_banned')::boolean, false), mr_until = coalesce(p ->> 'mr_until', ''),
            pl_banned = coalesce((p ->> 'pl_banned')::boolean, false), pl_until = coalesce(p ->> 'pl_until', ''),
            withdrawn = coalesce((p ->> 'withdrawn')::boolean, false), note = coalesce(p ->> 'note', ''),
            worker_id = v_worker, version = version + 1, updated_at = now()
        where id = v_id;
        perform _log('계정 수정', _acc_label(v_id));
    end if;

    delete from characters where account_id = v_id;
    for c in select * from jsonb_array_elements(coalesce(p -> 'characters', '[]'::jsonb)) loop
        if trim(coalesce(c ->> 'nickname', '')) <> '' or trim(coalesce(c ->> 'level_job', '')) <> '' then
            insert into characters (account_id, game, nickname, level_job, sort)
            values (v_id, c ->> 'game', trim(coalesce(c ->> 'nickname', '')), trim(coalesce(c ->> 'level_job', '')), i);
            i := i + 1;
        end if;
    end loop;

    if coalesce((p ->> 'withdrawn')::boolean, false) then
        delete from assignments where account_id = v_id;
    end if;
    return v_id;
end $$;

create or replace function public.delete_account(p_id bigint) returns void
language plpgsql security definer set search_path = public as $$
declare v_label text;
begin
    if not (is_admin() or (can_see_account(p_id) and has_perm('delete_account'))) then
        raise exception '이 계정을 삭제할 권한이 없어요.';
    end if;
    v_label := _acc_label(p_id);
    delete from accounts where id = p_id;
    perform _log('계정 삭제', v_label);
end $$;

-- ============================================================ 컴퓨터
create or replace function public.save_pc(p jsonb) returns bigint
language plpgsql security definer set search_path = public as $$
declare
    v_id     bigint := nullif(p ->> 'id', '')::bigint;
    v_no     integer := (p ->> 'no')::integer;
    v_slots  integer := coalesce((p ->> 'slot_count')::integer, 2);
    v_cur    pcs%rowtype;
    v_worker uuid;
    v_over   text;
begin
    if v_slots < 1 then raise exception '자리 수는 1 이상이어야 해요.'; end if;
    if v_id is null then
        if not is_admin() then raise exception '컴퓨터 추가는 관리자만 할 수 있어요.'; end if;
        v_worker := nullif(p ->> 'worker_id', '')::uuid;
    else
        select * into v_cur from pcs where id = v_id for update;
        if not found then raise exception '없는 컴퓨터예요. 새로고침한 뒤 다시 시도하세요.'; end if;
        if not (is_admin() or (v_cur.worker_id = auth.uid() and has_perm('edit_pc'))) then
            raise exception '이 컴퓨터 정보를 수정할 권한이 없어요.';
        end if;
        if v_cur.version <> coalesce((p ->> 'version')::integer, -1) then
            raise exception '다른 사람이 먼저 이 컴퓨터 정보를 수정했어요. 새로고침한 뒤 다시 수정하세요.';
        end if;
        v_worker := case when is_admin() then nullif(p ->> 'worker_id', '')::uuid else v_cur.worker_id end;
        select string_agg(slot || '자리', ', ' order by slot) into v_over
            from assignments where pc_id = v_id and slot > v_slots;
        if v_over is not null then
            raise exception '줄이려는 자리에 계정이 들어 있어요. 먼저 그 계정을 빼세요: %', v_over;
        end if;
    end if;
    if exists (select 1 from pcs where no = v_no and id is distinct from v_id) then
        raise exception '%번 컴퓨터가 이미 있어요.', v_no;
    end if;

    if v_id is null then
        insert into pcs (no, name, remote_t, anydesk_id, anydesk_pw, vpn, ld_cloud, slot_count, note, worker_id)
        values (v_no, trim(coalesce(p ->> 'name', '')), trim(coalesce(p ->> 'remote_t', '')),
                trim(coalesce(p ->> 'anydesk_id', '')), coalesce(p ->> 'anydesk_pw', ''), trim(coalesce(p ->> 'vpn', '')),
                trim(coalesce(p ->> 'ld_cloud', '')), v_slots, coalesce(p ->> 'note', ''), v_worker)
        returning id into v_id;
        perform _log('컴퓨터 추가', format('%s. %s', v_no, p ->> 'name'));
    else
        update pcs set no = v_no, name = trim(coalesce(p ->> 'name', '')), remote_t = trim(coalesce(p ->> 'remote_t', '')),
            anydesk_id = trim(coalesce(p ->> 'anydesk_id', '')), anydesk_pw = coalesce(p ->> 'anydesk_pw', ''),
            vpn = trim(coalesce(p ->> 'vpn', '')), ld_cloud = trim(coalesce(p ->> 'ld_cloud', '')),
            slot_count = v_slots, note = coalesce(p ->> 'note', ''), worker_id = v_worker,
            version = version + 1, updated_at = now()
        where id = v_id;
        perform _log('컴퓨터 수정', format('%s. %s', v_no, p ->> 'name'));
    end if;
    return v_id;
end $$;

create or replace function public.delete_pc(p_id bigint) returns void
language plpgsql security definer set search_path = public as $$
declare v_label text;
begin
    if not is_admin() then raise exception '컴퓨터 삭제는 관리자만 할 수 있어요.'; end if;
    select format('%s. %s', no, name) into v_label from pcs where id = p_id;
    delete from pcs where id = p_id;
    perform _log('컴퓨터 삭제', coalesce(v_label, '') || ' (들어 있던 계정은 사용가능으로 돌아감)');
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
    if not owns_pc(p_pc) then raise exception '담당 컴퓨터가 아니에요.'; end if;
    select * into v_acc from accounts where id = p_account;
    if not found then raise exception '없는 계정이에요. 새로고침한 뒤 다시 시도하세요.'; end if;
    if not (is_admin() or v_acc.worker_id = auth.uid()) then raise exception '담당 계정이 아니에요.'; end if;
    if v_acc.withdrawn then raise exception '탈퇴한 계정은 넣을 수 없어요.'; end if;
    select pc_id, slot into v_where from assignments where account_id = p_account;
    if found then
        raise exception '이 계정은 이미 %에 들어 있어요.', _pc_label(v_where.pc_id, v_where.slot);
    end if;
    begin
        insert into assignments (pc_id, slot, account_id) values (p_pc, p_slot, p_account);
    exception when unique_violation then
        raise exception '그 자리에 이미 다른 계정이 들어갔어요. 새로고침한 뒤 다시 시도하세요.';
    end;
    perform _log('배정', _pc_label(p_pc, p_slot) || ' ← ' || _acc_label(p_account));
end $$;

create or replace function public.unassign_slot(p_pc bigint, p_slot integer) returns void
language plpgsql security definer set search_path = public as $$
declare v_acc bigint;
begin
    if not owns_pc(p_pc) then raise exception '담당 컴퓨터가 아니에요.'; end if;
    delete from assignments where pc_id = p_pc and slot = p_slot returning account_id into v_acc;
    if v_acc is not null then
        perform _log('빼기', _pc_label(p_pc, p_slot) || ' → ' || _acc_label(v_acc));
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
    if not (owns_pc(v_src.pc_id) and owns_pc(p_pc)) then raise exception '담당 컴퓨터끼리만 옮길 수 있어요.'; end if;
    select * into v_pc from pcs where id = p_pc;
    if not found or p_slot < 1 or p_slot > v_pc.slot_count then raise exception '없는 자리예요.'; end if;
    begin
        update assignments set pc_id = p_pc, slot = p_slot, assigned_at = now() where account_id = p_account;
    exception when unique_violation then
        raise exception '옮길 자리에 이미 계정이 있어요. 새로고침한 뒤 다시 시도하세요.';
    end;
    perform _log('옮기기', _acc_label(p_account) || ': ' || _pc_label(v_src.pc_id, v_src.slot) || ' → ' || _pc_label(p_pc, p_slot));
end $$;

-- ============================================================ 근무자 관리 (관리자)
create or replace function public.save_profile(p jsonb) returns void
language plpgsql security definer set search_path = public as $$
declare
    v_id   uuid := (p ->> 'id')::uuid;
    v_role text := p ->> 'role';
begin
    if not is_admin() then raise exception '관리자만 할 수 있어요.'; end if;
    if v_role not in ('admin', 'worker', 'pending') then raise exception '알 수 없는 역할이에요.'; end if;
    if v_role <> 'admin' and exists (select 1 from profiles where id = v_id and role = 'admin')
       and (select count(*) from profiles where role = 'admin') <= 1 then
        raise exception '관리자가 한 명은 있어야 해요.';
    end if;
    update profiles set
        display_name = coalesce(nullif(trim(p ->> 'display_name'), ''), display_name),
        role = v_role,
        can_add_account = coalesce((p ->> 'can_add_account')::boolean, false),
        can_edit_account = coalesce((p ->> 'can_edit_account')::boolean, false),
        can_delete_account = coalesce((p ->> 'can_delete_account')::boolean, false),
        can_edit_pc = coalesce((p ->> 'can_edit_pc')::boolean, false)
    where id = v_id;
    perform _log('근무자 설정', format('%s: %s', p ->> 'display_name', v_role));
end $$;

-- ============================================================ 팀 암호(비번 암호화 키) 설정
create or replace function public.set_team_key(p_salt text, p_check text) returns void
language plpgsql security definer set search_path = public as $$
begin
    if not is_admin() then raise exception '관리자만 할 수 있어요.'; end if;
    if exists (select 1 from app_settings where key = 'key_salt') then
        raise exception '팀 암호가 이미 설정돼 있어요.';
    end if;
    insert into app_settings (key, value) values ('key_salt', p_salt), ('key_check', p_check);
    perform _log('팀 암호 설정', '');
end $$;

-- ============================================================ 변경 감지 (자동 새로고침용)
create or replace function public.last_change() returns bigint
language sql stable security definer set search_path = public as $$
    select case when is_member() then coalesce((select max(id) from audit_log), 0) else 0 end
$$;

-- ============================================================ 엑셀/로컬 데이터 한꺼번에 올리기 (관리자)
-- p = {"accounts":[{..., "characters":[...]}], "pcs":[{...}], "links":[{"pc_no":1,"slot":1,"acc":0}]}
create or replace function public.import_data(p jsonb) returns integer
language plpgsql security definer set search_path = public as $$
declare
    a      jsonb;
    pc     jsonb;
    l      jsonb;
    c      jsonb;
    idx    integer := 0;
    k      integer;
    v_id   bigint;
    ids    bigint[] := '{}';
    n_link integer := 0;
begin
    if not is_admin() then raise exception '관리자만 할 수 있어요.'; end if;
    -- 'where true': Supabase의 safeupdate가 조건 없는 delete를 막기 때문
    delete from assignments where true;
    delete from characters where true;
    delete from accounts where true;
    delete from pcs where true;

    for a in select * from jsonb_array_elements(p -> 'accounts') loop
        insert into accounts (owner, contact, provider, login_id, login_key, password, tag,
                              mr_banned, mr_until, pl_banned, pl_until, withdrawn, note, worker_id)
        values (coalesce(a ->> 'owner', ''), coalesce(a ->> 'contact', ''), coalesce(a ->> 'provider', ''),
                trim(a ->> 'login_id'), lower(trim(a ->> 'login_id')), coalesce(a ->> 'password', ''),
                coalesce(a ->> 'tag', ''), coalesce((a ->> 'mr_banned')::boolean, false), coalesce(a ->> 'mr_until', ''),
                coalesce((a ->> 'pl_banned')::boolean, false), coalesce(a ->> 'pl_until', ''),
                coalesce((a ->> 'withdrawn')::boolean, false), coalesce(a ->> 'note', ''),
                nullif(a ->> 'worker_id', '')::uuid)
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
        insert into pcs (no, name, remote_t, anydesk_id, anydesk_pw, vpn, ld_cloud, slot_count, note, worker_id)
        values ((pc ->> 'no')::integer, coalesce(pc ->> 'name', ''), coalesce(pc ->> 'remote_t', ''),
                coalesce(pc ->> 'anydesk_id', ''), coalesce(pc ->> 'anydesk_pw', ''), coalesce(pc ->> 'vpn', ''),
                coalesce(pc ->> 'ld_cloud', ''), coalesce((pc ->> 'slot_count')::integer, 2), coalesce(pc ->> 'note', ''),
                nullif(pc ->> 'worker_id', '')::uuid);
    end loop;

    for l in select * from jsonb_array_elements(p -> 'links') loop
        insert into assignments (pc_id, slot, account_id)
        select id, (l ->> 'slot')::integer, ids[(l ->> 'acc')::integer + 1]
        from pcs where no = (l ->> 'pc_no')::integer
        on conflict do nothing;
        get diagnostics k = row_count;
        n_link := n_link + k;
    end loop;

    perform _log('데이터 올리기', format('계정 %s개, 컴퓨터 %s대, 배정 %s건',
        jsonb_array_length(p -> 'accounts'), jsonb_array_length(p -> 'pcs'), n_link));
    return n_link;
end $$;

-- ============================================================ 테이블 접근 권한
-- 프로젝트 생성 시 'Grant API access to new tables automatically'를 끈 경우에도 동작하도록 직접 지정한다.
-- 로그인한 사용자(authenticated)는 읽기만 가능(실제로 보이는 행은 위의 RLS가 결정), 로그인 안 한 사용자(anon)는 접근 불가.
grant usage on schema public to authenticated;
revoke all on public.profiles, public.pcs, public.accounts, public.characters,
              public.assignments, public.audit_log, public.app_settings from anon, authenticated;
grant select on public.profiles, public.pcs, public.accounts, public.characters,
                public.assignments, public.audit_log, public.app_settings to authenticated;

-- ============================================================ 실행 권한
revoke execute on all functions in schema public from public, anon;
grant execute on function
    public.my_role(), public.is_admin(), public.is_member(), public.has_perm(text),
    public.can_see_account(bigint), public.owns_pc(bigint),
    public.save_account(jsonb), public.delete_account(bigint),
    public.save_pc(jsonb), public.delete_pc(bigint),
    public.assign_account(bigint, integer, bigint), public.unassign_slot(bigint, integer),
    public.move_account(bigint, bigint, integer),
    public.save_profile(jsonb), public.set_team_key(text, text),
    public.last_change(), public.import_data(jsonb)
to authenticated;
