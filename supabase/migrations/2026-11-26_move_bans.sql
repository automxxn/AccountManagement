-- 메랜정지 정보를 전부 플래닛정지로 옮기고, 기존 플래닛정지 정보는 지운다 (사용자 요청 2026-11-26).
-- 엑셀을 가져올 때 IDPW의 정지 날짜를 메랜정지로 잘못 넣었던 것을 바로잡는다.
-- 한 번만 적용된다: 다시 실행해도 아무것도 바뀌지 않는다.
do $$
begin
    if exists (select 1 from public.app_settings where key = 'migration_move_bans_20261126') then
        raise notice '이미 적용됨';
        return;
    end if;

    update public.accounts set
        pl_banned  = mr_banned,
        pl_until   = mr_until,
        mr_banned  = false,
        mr_until   = '',
        note       = replace(note, '[메랜정지 칸]', '[플래닛정지 칸]'),
        version    = version + 1,
        updated_at = now()
    where true;

    insert into public.app_settings (key, value) values ('migration_move_bans_20261126', now()::text);
    insert into public.audit_log (actor, action, detail)
    values ('관리자(SQL)', '정지 정보 이동', '메랜정지 → 플래닛정지 (기존 플래닛정지는 지움)');
end $$;
