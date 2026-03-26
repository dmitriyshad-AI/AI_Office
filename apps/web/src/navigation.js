export const OFFICE_NAV_ITEMS = [
  { id: "director", path: "/director", label: "Директор" },
  { id: "team", path: "/team", label: "Команда" },
  { id: "runs", path: "/runs", label: "Запуски" },
  { id: "events", path: "/events", label: "События" },
  { id: "approvals", path: "/approvals", label: "Одобрения" },
  { id: "artifacts", path: "/artifacts", label: "Артефакты" },
];

export const MODULE_REGISTRY = [
  {
    id: "crm",
    path: "/crm",
    label: "CRM",
    title: "CRM и клиенты",
    status: "active",
    description: "Tallanto -> AMO с превью, ручной проверкой и точечной отправкой.",
    keywords: ["crm", "amo", "tallanto", "client", "student", "lead"],
  },
  {
    id: "calls",
    path: "/calls",
    label: "Звонки",
    title: "Звонки и Mango",
    status: "active",
    description: "Локальная расшифровка, QA разговоров и догрузка сигналов в AMO.",
    keywords: ["mango", "звон", "разговор", "call", "phone", "telephony", "телефон"],
  },
];

export const MODULE_NAV_ITEMS = MODULE_REGISTRY.map(({ id, path, label, status }) => ({
  id,
  path,
  label,
  status,
}));

export const MODULE_STATUS_LABELS = {
  active: "Работает",
  planned: "Готовится",
};
