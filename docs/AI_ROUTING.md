# Routing koszt / jakość
1. Cache: klucz zawiera hash źródeł, as_of, prompt, model i wersję polityki; TTL zależny od danych. Nie używaj cache innego tenant.
2. Python/deterministyczna metoda jeśli spełnia wymagania zadania.
3. Modele z dopuszczonymi capabilities, polityką danych i aktualną ewaluacją. Sortuj według całego szacowanego kosztu: input/output tokens, cache, retry, retrieval, GPU/czas, energia/hosting i opłaty narzędzi. Lokalny model nie jest automatycznie darmowy.
4. Zarezerwuj najgorszy dopuszczony koszt atomowo dla job/day/month; rozlicz faktyczne zużycie i zwolnij rezerwę. Brak ceny lub limitu = provider wyłączony. Wyczerpanie budżetu = queued/blocked, bez automatycznego zakupu.
5. JSON schema, pokrycie cytowań, poprawność liczb i ocena golden set są bramką. Eskaluj po mierzalnym błędzie, do max_attempts; zapisz powód. Model nie ocenia sam swojej jakości.
config/models.json nie zawiera bieżących cen. Operator dostarcza price sheet z walutą, jednostką, datą i źródłem, a evaluator jakość. Nie zakładaj że najmniejsza cena tokena minimalizuje koszt zadania.
Nowy provider: implementuj services/runtime/providers/base.mjs, uzupełnij capabilities i timeout, mapuj błędy/usage, dodaj fake test oraz integration test opt-in. Sekrety wyłącznie serwer. OpenAI/Anthropic/Gemini/Ollama mają placeholdery; żadna integracja nie jest udawana.
