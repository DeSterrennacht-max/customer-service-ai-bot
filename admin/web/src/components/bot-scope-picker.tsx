"use client";

import { BotProfile } from "@/types/api";

interface BotScopePickerProps {
  bots: BotProfile[];
  value: string;
  onChange: (botProfileId: string) => void;
  disabled?: boolean;
  label?: string;
  description?: string;
}

function formatBotLabel(bot: BotProfile): string {
  const tenantPrefix = bot.tenant_name ? `${bot.tenant_name} / ` : "";
  const username = bot.telegram_bot_username ? ` (@${bot.telegram_bot_username.replace(/^@+/, "")})` : "";
  return `${tenantPrefix}${bot.name}${username}`;
}

export function BotScopePicker({
  bots,
  value,
  onChange,
  disabled = false,
  label = "当前机器人",
  description = "当前页面的列表和保存操作都会基于这里选中的机器人。"
}: BotScopePickerProps) {
  if (bots.length === 0) {
    return null;
  }

  return (
    <div className="card">
      <strong>{label}</strong>
      <p>{description}</p>
      <label>
        机器人
        <select value={value} onChange={(event) => onChange(event.target.value)} disabled={disabled}>
          {bots.map((bot) => (
            <option key={bot.id} value={bot.id}>
              {formatBotLabel(bot)}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
