import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, type ClientSettings } from "../api";
import { Button, Dialog, ErrorNote, Field, Input, useToast } from "./ui";
import { DEFAULT_SETTINGS, SettingsFields } from "./ClientForm";

const GSTIN_RE = /^[0-9]{2}[A-Z0-9]{10}[0-9A-Z]Z[0-9A-Z]$/;

export function NewClientDialog({ open, onClose, period }: { open: boolean; onClose: () => void; period?: string }) {
  const [name, setName] = useState("");
  const [gstin, setGstin] = useState("");
  const [trade, setTrade] = useState("");
  const [settings, setSettings] = useState<ClientSettings>(DEFAULT_SETTINGS);
  const [gstinError, setGstinError] = useState<string | null>(null);
  const qc = useQueryClient();
  const nav = useNavigate();
  const toast = useToast();

  const create = useMutation({
    mutationFn: () => api.createClient({ name: name.trim(), gstin: gstin.trim().toUpperCase(), trade_name: trade.trim(), settings }),
    onSuccess: (c) => {
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      qc.invalidateQueries({ queryKey: ["clients"] });
      toast(`Added ${c.name}`, "ok");
      onClose();
      setName("");
      setGstin("");
      setTrade("");
      setSettings(DEFAULT_SETTINGS);
      if (period) nav(`/clients/${c.id}/${period}/overview`);
      else nav(`/clients/${c.id}`);
    },
    onError: (e) => {
      // The API validates the GSTIN (check digit etc.); show its message under the field.
      if (e instanceof ApiError && e.status === 400 && /gstin/i.test(e.message)) setGstinError(e.message);
    },
  });

  const g = gstin.trim().toUpperCase();
  const localHint = g.length > 0 && g.length !== 15 ? `${g.length} of 15 characters` : g.length === 15 && !GSTIN_RE.test(g) ? "This doesn't look like a GSTIN; the server will check it." : null;

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="New client"
      width={560}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" busy={create.isPending} disabled={!name.trim() || !g} onClick={() => create.mutate()}>
            Add client
          </Button>
        </>
      }
    >
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim() && g) create.mutate();
        }}
      >
        <Field label="Client name">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Sharma Auto Components Pvt Ltd" />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="GSTIN" error={gstinError} hint={localHint ?? "15 characters, e.g. 27AAACS1234F1Z5"}>
            <Input
              value={gstin}
              invalid={!!gstinError}
              maxLength={15}
              className="code uppercase"
              onChange={(e) => {
                setGstin(e.target.value.toUpperCase());
                setGstinError(null);
              }}
            />
          </Field>
          <Field label="Trade name (optional)">
            <Input value={trade} onChange={(e) => setTrade(e.target.value)} />
          </Field>
        </div>
        <SettingsFields value={settings} onChange={setSettings} />
        {create.error && !gstinError && <ErrorNote error={create.error} />}
        <button type="submit" hidden />
      </form>
    </Dialog>
  );
}
