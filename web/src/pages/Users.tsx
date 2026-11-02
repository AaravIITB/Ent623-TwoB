import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Role, type User } from "../api";
import { ROLE_LABEL, useUser } from "../lib/auth";
import { PageHeader } from "../components/Layout";
import { Button, Dialog, ErrorNote, Field, Input, Panel, Select, TableSkeleton, useToast } from "../components/ui";
import { IconPlus } from "../components/icons";

const ROLES: Role[] = ["preparer", "reviewer", "admin"];
const ROLE_TEXT: Record<Role, string> = {
  preparer: "Uploads, reconciles, decides, follows up and submits for review.",
  reviewer: "Everything a preparer does, plus approve, send back and close a month.",
  admin: "Everything, including users and deleting clients.",
};

export default function Users() {
  const me = useUser();
  const q = useQuery({ queryKey: ["users"], queryFn: api.users });
  const qc = useQueryClient();
  const toast = useToast();
  const [adding, setAdding] = useState(false);
  const [pwFor, setPwFor] = useState<User | null>(null);

  const update = useMutation({
    mutationFn: (v: { id: number; role?: Role; name?: string; password?: string; active?: boolean }) =>
      api.updateUser(v.id, { role: v.role, name: v.name, password: v.password, active: v.active }),
    onSuccess: (u, v) => {
      qc.invalidateQueries({ queryKey: ["users"] });
      toast(v.password ? "Password changed" : v.active === false ? `${u.name} can no longer sign in` : v.active ? `${u.name} can sign in again` : "User updated", "ok");
      setPwFor(null);
    },
    onError: (e) => toast((e as Error).message, "error"),
  });

  return (
    <div className="pb-10">
      <PageHeader
        title="Users"
        subtitle="People in your firm who can sign in to TwoB."
        actions={
          <Button variant="primary" onClick={() => setAdding(true)}>
            <IconPlus /> Add user
          </Button>
        }
      />
      <div className="px-6 grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px] items-start">
        <Panel flush title="All users">
          <ErrorNote error={q.error} />
          {q.isLoading ? (
            <TableSkeleton rows={4} cols={4} />
          ) : (
            <table className="tbl">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Username</th>
                  <th>Role</th>
                  <th>Access</th>
                  <th className="r" />
                </tr>
              </thead>
              <tbody>
                {(q.data ?? []).map((u) => (
                  <tr key={u.id} className={u.active === false ? "[&>td]:text-muted" : ""}>
                    <td className="font-medium">
                      {u.name}
                      {u.id === me.id && <span className="text-muted font-normal"> (you)</span>}
                    </td>
                    <td className="code text-sm">{u.username}</td>
                    <td>
                      <Select
                        aria-label={`Role for ${u.name}`}
                        value={u.role}
                        disabled={u.id === me.id}
                        title={u.id === me.id ? "You can't change your own role" : undefined}
                        onChange={(e) => update.mutate({ id: u.id, role: e.target.value as Role })}
                        className="h-7 text-sm w-36"
                      >
                        {ROLES.map((r) => (
                          <option key={r} value={r}>
                            {ROLE_LABEL[r]}
                          </option>
                        ))}
                      </Select>
                    </td>
                    <td>{u.active === false ? <span className="text-sm text-high">Disabled</span> : <span className="text-sm text-ok">Active</span>}</td>
                    <td className="r whitespace-nowrap">
                      <Button size="sm" variant="ghost" onClick={() => setPwFor(u)}>
                        Change password
                      </Button>
                      {u.active === false ? (
                        <Button size="sm" variant="ghost" onClick={() => update.mutate({ id: u.id, active: true })}>
                          Enable
                        </Button>
                      ) : (
                        <Button
                          size="sm"
                          variant="ghost"
                          className="!text-high"
                          disabledReason={u.id === me.id ? "You can't disable yourself." : null}
                          onClick={() => update.mutate({ id: u.id, active: false })}
                        >
                          Disable
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
        <Panel title="Roles">
          <dl className="space-y-3 text-sm">
            {ROLES.map((r) => (
              <div key={r}>
                <dt className="font-medium">{ROLE_LABEL[r]}</dt>
                <dd className="text-muted">{ROLE_TEXT[r]}</dd>
              </div>
            ))}
          </dl>
        </Panel>
      </div>
      <AddUserDialog open={adding} onClose={() => setAdding(false)} />
      <PasswordDialog user={pwFor} busy={update.isPending} onClose={() => setPwFor(null)} onSave={(pw) => pwFor && update.mutate({ id: pwFor.id, password: pw })} />
    </div>
  );
}

function AddUserDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [username, setUsername] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<Role>("preparer");
  const [password, setPassword] = useState("");
  const qc = useQueryClient();
  const toast = useToast();
  const add = useMutation({
    mutationFn: () => api.createUser({ username: username.trim(), name: name.trim(), role, password }),
    onSuccess: (u) => {
      qc.invalidateQueries({ queryKey: ["users"] });
      toast(`Added ${u.name}`, "ok");
      setUsername("");
      setName("");
      setPassword("");
      setRole("preparer");
      onClose();
    },
  });
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Add user"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" busy={add.isPending} disabled={!username.trim() || !name.trim() || password.length < 6} onClick={() => add.mutate()}>
            Add user
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <Field label="Full name">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Riya Sharma" />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Username">
            <Input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="off" />
          </Field>
          <Field label="Role">
            <Select value={role} onChange={(e) => setRole(e.target.value as Role)}>
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {ROLE_LABEL[r]}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <Field label="Password" hint="At least 6 characters. Share it with them directly.">
          <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
        </Field>
        <ErrorNote error={add.error} />
      </div>
    </Dialog>
  );
}

function PasswordDialog({ user, busy, onClose, onSave }: { user: User | null; busy: boolean; onClose: () => void; onSave: (pw: string) => void }) {
  const [pw, setPw] = useState("");
  return (
    <Dialog
      open={!!user}
      onClose={() => {
        setPw("");
        onClose();
      }}
      title={`New password for ${user?.name ?? ""}`}
      width={420}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            busy={busy}
            disabled={pw.length < 6}
            onClick={() => {
              onSave(pw);
              setPw("");
            }}
          >
            Change password
          </Button>
        </>
      }
    >
      <Field label="New password" hint="At least 6 characters.">
        <Input type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="new-password" />
      </Field>
    </Dialog>
  );
}
