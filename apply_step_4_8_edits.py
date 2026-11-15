"""Applies the small edits that Steps 4.8 and 4.9 need to 3 existing files.

Run from the repo root (the intentgrid folder):   python apply_step_4_8_edits.py
Safe to run twice. It keeps each file's line endings and never changes a file if a search text
is not found exactly once.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "backend"

EDITS = {
    "app/routers/contact.py": [
        ("from fastapi import APIRouter, Depends, Request, status",
         "from fastapi import APIRouter, BackgroundTasks, Depends, Request, status"),
        ("from app.security import client_ip, limiter",
         "from app.security import client_ip, limiter\nfrom app.workflow_trigger import get_workflow_starter"),
        ("    db: Session = Depends(get_db),",
         "    background_tasks: BackgroundTasks,\n    db: Session = Depends(get_db),\n"
         "    start_workflow=Depends(get_workflow_starter),"),
        ("    ticket_repo.create_ticket(db, data, ip_hash=ip_hash)",
         "    ticket = ticket_repo.create_ticket(db, data, ip_hash=ip_hash)\n"
         "    background_tasks.add_task(start_workflow, ticket.id)"),
    ],
    "app/main.py": [
        ("from app.routers import contact, tickets",
         "from app.routers import contact, internal, reprocess, tickets"),
        ("app.include_router(tickets.router, dependencies=[Depends(require_api_key)])",
         "app.include_router(tickets.router, dependencies=[Depends(require_api_key)])\n"
         "app.include_router(reprocess.router, dependencies=[Depends(require_api_key)])\n"
         "app.include_router(internal.router, dependencies=[Depends(require_api_key)])"),
    ],
    "tests/conftest.py": [
        ("    from app.security import limiter",
         "    from app.security import limiter\n    from app.workflow_trigger import get_workflow_starter"),
        ("    app.dependency_overrides[get_db] = override_get_db",
         "    app.dependency_overrides[get_db] = override_get_db\n"
         "    app.dependency_overrides[get_workflow_starter] = lambda: (lambda ticket_id, claimed=False: None)"),
    ],
}
DONE_MARKER = {
    "app/routers/contact.py": "get_workflow_starter",
    "app/main.py": "reprocess.router",
    "tests/conftest.py": "get_workflow_starter",
}


def main() -> int:
    problems = 0
    for rel, edits in EDITS.items():
        path = ROOT / rel
        if not path.exists():
            print(f"MISSING  {rel}  (run this from the intentgrid folder)")
            problems += 1
            continue
        raw = path.read_bytes()
        has_bom = raw.startswith(b"\xef\xbb\xbf")
        text = raw.decode("utf-8-sig")
        if DONE_MARKER[rel] in text:
            print(f"already  {rel}")
            continue
        newline = "\r\n" if "\r\n" in text else "\n"
        new_text = text
        ok = True
        for old, new in edits:
            if new_text.count(old) != 1:
                print(f"SKIPPED  {rel}: expected exactly one match of: {old.strip()!r} "
                      f"(found {new_text.count(old)})")
                ok = False
                break
            new_text = new_text.replace(old, new.replace("\n", newline))
        if not ok:
            problems += 1
            continue
        out = new_text.encode("utf-8")
        path.write_bytes((b"\xef\xbb\xbf" + out) if has_bom else out)
        print(f"edited   {rel}")
    if problems:
        print(f"\n{problems} file(s) not edited. Paste this output to Claude.")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
