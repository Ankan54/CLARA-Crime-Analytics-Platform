import { useEffect, useRef, useState } from "react";
import { FIXED_DEMO_USER } from "../config/demoUser";

export function UserProfileMenu() {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    function handleClickAway(event: MouseEvent): void {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickAway);
    return () => document.removeEventListener("mousedown", handleClickAway);
  }, []);

  return (
    <div className="user-profile-menu" ref={rootRef}>
      <button
        type="button"
        className="user-profile-trigger"
        onClick={() => setOpen((current) => !current)}
        aria-haspopup="true"
        aria-expanded={open}
        title={`${FIXED_DEMO_USER.rank} ${FIXED_DEMO_USER.name}`}
      >
        <img src="/police-icon.PNG" alt="" className="user-profile-avatar-img" />
      </button>
      {open && (
        <div className="user-profile-popover" aria-label="Officer profile details">
          <strong>
            {FIXED_DEMO_USER.rank} {FIXED_DEMO_USER.name}
          </strong>
          <span>{FIXED_DEMO_USER.station}</span>
          <span className="mono">{FIXED_DEMO_USER.kgid}</span>
        </div>
      )}
    </div>
  );
}
