# Calls Module Integration Spec

## 1. Цель

`Звонки` — второй доменный модуль `AI Office`.

Он не должен заново изобретать обработку телефонии. Его задача — аккуратно встроить уже существующий проект
`/Users/dmitrijfabarisov/Projects/Mango analyse` в архитектуру `AI Office`.

Правильная модель:

- `Mango analyse` остается локальным processing engine на `MacBook`;
- `AI Office` становится слоем оркестрации, review queue, аудита и безопасной записи в `amoCRM`;
- сервер `AI Office` не делает тяжелую обработку аудио и не подменяет зрелый локальный pipeline.

## 2. Что уже есть в Mango analyse

Проект уже покрывает почти весь локальный цикл обработки звонков:

- ingest файлов и метаданных:
  - [ingest.py](/Users/dmitrijfabarisov/Projects/Mango%20analyse/src/mango_mvp/services/ingest.py)
- транскрибация и dual-ASR:
  - [transcribe.py](/Users/dmitrijfabarisov/Projects/Mango%20analyse/src/mango_mvp/services/transcribe.py)
- resolve и dialogue-level cleanup:
  - [resolve.py](/Users/dmitrijfabarisov/Projects/Mango%20analyse/src/mango_mvp/services/resolve.py)
- LLM-анализ и построение CRM-ready структуры:
  - [analyze.py](/Users/dmitrijfabarisov/Projects/Mango%20analyse/src/mango_mvp/services/analyze.py)
- циклический worker:
  - [worker.py](/Users/dmitrijfabarisov/Projects/Mango%20analyse/src/mango_mvp/services/worker.py)
- локальная модель данных:
  - [models.py](/Users/dmitrijfabarisov/Projects/Mango%20analyse/src/mango_mvp/models.py)
- прямой sync в `amoCRM`:
  - [sync_amocrm.py](/Users/dmitrijfabarisov/Projects/Mango%20analyse/src/mango_mvp/services/sync_amocrm.py)
  - [amocrm.py](/Users/dmitrijfabarisov/Projects/Mango%20analyse/src/mango_mvp/clients/amocrm.py)
- отдельная локальная GUI:
  - [gui.py](/Users/dmitrijfabarisov/Projects/Mango%20analyse/src/mango_mvp/gui.py)

Это уже не черновик, а рабочий pipeline с CLI, GUI, SQLite, retry/dead-letter и тестами.

## 3. Что переиспользуем, а что нет

### Переиспользуем почти как есть

- ingest-логику
- transcribe pipeline
- resolve pipeline
- analyze pipeline
- worker/stage model
- экспорт промежуточных артефактов и review queues

Это зрелые локальные слои, и их нет смысла переписывать в `AI Office`.

### Переиспользуем через адаптер

- `analysis_json` как источник канонического `Call Insight Payload`
- CLI/worker как entrypoint локальной обработки
- SQLite как локальное хранилище processing state

Здесь нужен мост между `Mango analyse` и `AI Office`, а не дублирование логики.

### Не переносим напрямую

- [gui.py](/Users/dmitrijfabarisov/Projects/Mango%20analyse/src/mango_mvp/gui.py)
- прямой `sync_amocrm` по телефону
- локальную GUI-модель как пользовательский интерфейс офиса

Причина: `AI Office` уже имеет свой UX, а прямой sync по телефону не соответствует вашей бизнес-модели
`один родитель -> несколько учеников`.

## 4. Главный архитектурный вывод

Неправильный путь:

- копировать проект звонков целиком в `AI Office`;
- переносить его GUI;
- дублировать ASR/resolve/analyze внутри backend `AI Office`;
- оставить прямой `sync_amocrm` по телефону.

Правильный путь:

1. оставить `Mango analyse` отдельным локальным engine;
2. дать ему экспортировать уже обработанные `call insights`;
3. научить `AI Office` принимать эти insights;
4. делать match и запись в `amoCRM` уже в `AI Office`.

## 5. Почему нельзя просто оставить текущий sync_amocrm

Текущий sync ищет контакт в `amoCRM` по телефону:

- [find_contact_by_phone](/Users/dmitrijfabarisov/Projects/Mango%20analyse/src/mango_mvp/clients/amocrm.py)
- [AmoCRMSyncService.run](/Users/dmitrijfabarisov/Projects/Mango%20analyse/src/mango_mvp/services/sync_amocrm.py)

Для вашей реальной модели это риск:

- у брата и сестры может быть один телефон родителя;
- один и тот же номер не идентифицирует ученика однозначно;
- значит, прямой write по телефону может ошибочно писать историю звонка не в ту карточку.

Следствие:

- прямой `sync_amocrm` в текущем виде нельзя считать финальным production-путем;
- его надо заменить на controlled intake + match + review queue внутри `AI Office`.

## 6. Канонический Call Insight Payload V1

Ниже — пакет, который должен принимать `AI Office` от локального Mango engine.

```json
{
  "schema_version": "call_insight_v1",
  "source": {
    "system": "mango_analyse",
    "call_record_id": 123,
    "source_call_id": "987654",
    "source_file": "/abs/path/to/file.mp3",
    "source_filename": "2026-03-01__10-00-00__79990000000__Иванов Иван_1.mp3",
    "started_at": "2026-03-01T10:00:00Z",
    "duration_sec": 298.5,
    "direction": "outbound",
    "manager_name": "Иванов Иван",
    "phone": "+79990000000"
  },
  "processing": {
    "transcription_status": "done",
    "resolve_status": "done",
    "analysis_status": "done",
    "resolve_quality_score": 88.0
  },
  "identity_hints": {
    "phone": "+79990000000",
    "parent_fio": "Иванова Анна",
    "child_fio": "Петр Иванов",
    "email": "test@example.com",
    "grade_current": "9",
    "school": "Школа 1",
    "preferred_channel": "telegram"
  },
  "call_summary": {
    "history_summary": "Краткая CRM-ready сводка звонка",
    "history_short": "Короткая сводка",
    "evidence": [
      {
        "speaker": "Клиент",
        "ts": "00:32.1",
        "text": "Нас интересует математика для 9 класса"
      }
    ]
  },
  "sales_insight": {
    "interests": {
      "products": ["годовые курсы"],
      "format": ["онлайн"],
      "subjects": ["математика"],
      "exam_targets": ["ОГЭ"]
    },
    "commercial": {
      "price_sensitivity": "medium",
      "budget": "до 100000",
      "discount_interest": true
    },
    "objections": ["цена"],
    "next_step": {
      "action": "Перезвонить",
      "due": "2026-03-10"
    },
    "lead_priority": "warm",
    "follow_up_score": 72,
    "follow_up_reason": "Нужен контакт на этой неделе",
    "personal_offer": null,
    "pain_points": ["цена"],
    "tags": ["follow_up"]
  },
  "quality_flags": {
    "stereo_mode": "split",
    "same_ts_cross": 0,
    "non_conversation": false
  },
  "raw_analysis": {}
}
```

## 7. Откуда брать поля для payload

Источники уже есть в проекте:

- базовая мета звонка:
  - [CallRecord](/Users/dmitrijfabarisov/Projects/Mango%20analyse/src/mango_mvp/models.py)
- нормализованная аналитика:
  - [AnalyzeService._normalize_analysis](/Users/dmitrijfabarisov/Projects/Mango%20analyse/src/mango_mvp/services/analyze.py)
- CSV/JSON экспорт CRM-ready полей:
  - [cmd_export_crm_fields](/Users/dmitrijfabarisov/Projects/Mango%20analyse/src/mango_mvp/cli.py)

Фактически `analysis_json` уже содержит почти всё, что нужно для `Call Insight Payload`.

## 8. Что должен делать AI Office с этим payload

`AI Office` после получения payload должен:

1. создать `call insight artifact`;
2. найти кандидатов в `amoCRM` по телефону;
3. усилить match по:
   - `child_fio`
   - `parent_fio`
   - `grade_current`
   - существующим данным `Tallanto`
   - уже связанным `Id Tallanto`, если он есть в контакте
4. принять одно из решений:
   - `matched_single_contact`
   - `new_student_in_family`
   - `manual_review_required`
   - `not_enough_data`
5. записать результат в `amoCRM` только после контролируемого match.

## 9. Матчинг для звонков

Порядок:

1. `phone` как стартовый ключ
2. список кандидатов по телефону
3. усиление по содержанию звонка и `identity_hints`
4. если кандидат ровно один и уверенность высокая — запись
5. если кандидатов несколько — ручная очередь

Запрещено:

- автоматически считать одинаковый телефон = тот же ученик
- автоматически сливать карточки по родительскому номеру

## 10. Что писать в amoCRM

Для звонков безопасно писать:

- `Авто история общения`
- `AI-сводка звонка`
- `Интересы`
- `Целевой продукт`
- `Приоритет`
- `Следующий шаг`
- `Причина follow-up`
- `Теги AI`
- при необходимости задачу менеджеру

Нельзя автоматически переписывать:

- стандартный `Телефон`
- стандартный `Email`
- ручные комментарии менеджеров
- старую ручную историю общения

## 11. Новый интеграционный разрез

V1 для интеграции должен выглядеть так:

### На стороне Mango analyse

- локальная обработка файла;
- сохранение `CallRecord` и `analysis_json`;
- экспорт `Call Insight Payload` через CLI-команду или adapter-script.

### На стороне AI Office

- `POST /projects/{id}/calls/insights`
- `GET /projects/{id}/calls/insights`
- `GET /projects/{id}/calls/review-queue`
- `POST /projects/{id}/calls/review-queue/{case_id}/resolve`

### На стороне UI

Модуль `Звонки` должен показывать:

- входящие insights;
- статус матчинга;
- спорные кейсы;
- решение по каждому звонку;
- итог записи в `amoCRM`.

## 12. Практический план внедрения

### Шаг 1

Сделать в `AI Office` server intake schema для `Call Insight Payload`.

Статус: выполнено.

### Шаг 2

Сделать в `Mango analyse` экспорт одного обработанного звонка в этот schema-format.

Статус: выполнено.

### Шаг 3

Поднять в `AI Office` review queue для неоднозначного match.

Статус: выполнено на backend-уровне.

### Шаг 4

Перевести запись в `amoCRM` из прямого `sync_amocrm` в controlled writer внутри `AI Office`.

Статус: выполнено в аккаунт-ориентированном mapping-режиме, требует доведения под реальную схему `amoCRM` и OAuth.

### Шаг 5

Вывести review queue и controlled write в полноценный UI и только после этого подключать массовый поток звонков.

Статус: базовый UI выведен, нужен следующий слой для массовой ручной обработки и операторской очереди.

## 13. Честный ответ на вопрос про “скопировать модули”

Частично.

Правильный подход такой:

- не копировать проект целиком;
- не переносить GUI и не дублировать зрелый локальный pipeline;
- использовать существующий проект как источник готовых локальных call insights;
- в `AI Office` переносить только интеграционную границу, match, review и controlled write.

То есть:

- `Mango analyse` остается отдельным локальным engine;
- `AI Office` становится его управляющим и интеграционным слоем.
