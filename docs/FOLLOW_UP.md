# Follow-up — cose da completare in una sessione apposita

Questo documento elenca tutto quello che il piano [`baba-node-api-extensions.md`](../README.md)
prevede ma che **non** è stato eseguibile in questa sessione, con i dettagli
operativi necessari per chiuderlo da un'altra sessione (con accesso a un
nodo Credits, alle dipendenze di build native e a permessi GitHub estesi).

Stato attuale del branch `claude/baba-node-api-extensions-DYS0c`:

- Tutti i mapper, codec e builder delle sezioni 1, 2, 3, 4, 6 del piano sono
  implementati in `services/*` e coperti da pytest (50/50 verdi).
- Tutti gli endpoint REST corrispondenti sono registrati in `gateway.py`
  con doppia route `/<path>` e `/api/<path>` e rate-limit allineato
  allo stile esistente.
- `.env.example` punta `NODE_IP=38.242.234.47` (nodo gestito).
- README.md aggiornato con tabelle, schema `userFields v1` ed esempi `curl`.

Quanto resta da fare richiede uno o più dei seguenti:

- shell con `gevent`, `thrift`, `redis` installabili (compilazione C richiesta);
- `gen-py/` generato da `CREDITSCOM/thrift-interface-definitions`;
- accesso a un nodo Credits di testnet/mainnet (es. `38.242.234.47:9090`);
- permessi GitHub per fork + PR su `molaanaa/baba-node-api` (lo scope MCP
  di questa sessione è limitato a `EnzinoBB/baba-node-api`).

---

## A. Generazione stub Thrift e ambiente runtime

1. Generare il pacchetto Python dai file `.thrift` ufficiali, da committare
   come submodule (Step 2 del piano):

   ```bash
   git submodule add https://github.com/CREDITSCOM/thrift-interface-definitions \
     thrift/interface
   cd thrift/interface
   git checkout <SHA fissato per riproducibilità>
   thrift -r --gen py api.thrift
   thrift -r --gen py apidiag.thrift     # per Sezione 6
   thrift -r --gen py apiexec.thrift     # per builder Methods
   cp -r gen-py ../../
   ```

   Risultato atteso: la directory `gen-py/` esposta da
   `sys.path.append('gen-py')` in `gateway.py:31` deve esistere e contenere
   almeno i moduli `api`, `apidiag`, `general`, `variant`, `executor`.

2. Installare le dipendenze runtime mancanti (questa sessione non riusciva
   a compilare `thrift` e `gevent`):

   ```bash
   sudo apt install -y python3-dev build-essential
   pip3 install -r requirements.txt
   ```

3. `pm2 restart baba-node-api` per ricaricare il gateway.

---

## B. Verifiche end-to-end contro il nodo gestito (38.242.234.47:9090)

Tutti i nuovi endpoint devono essere validati con un nodo reale o con un
mock Thrift completo. Sequenza minima di smoke test (Step 8 del piano):

```bash
HOST=http://localhost:5000

# 1. UserFields codec round-trip (locale, non richiede nodo)
curl -s -X POST $HOST/api/UserFields/Encode \
  -H 'Content-Type: application/json' \
  -d '{"contentHashAlgo":"sha-256","contentHash":"00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff","contentCid":"bafybeigdyrabc","mime":"image/png","sizeBytes":1234567}'
# -> { success: true, userData: "<base58>" }
curl -s -X POST $HOST/api/UserFields/Decode \
  -H 'Content-Type: application/json' \
  -d '{"userData":"<base58 from prev>"}'
# -> { success: true, fields: { ... originali ... } }

# 2. Token info su un token noto del nodo
curl -s -X POST $HOST/api/Tokens/Info \
  -H 'Content-Type: application/json' \
  -d '{"token":"<base58 token address>"}'

# 3. Long-poll: deve restituire 200 entro WAIT_DEFAULT_TIMEOUT_MS quando
#    arriva un nuovo blocco
curl -s -X POST $HOST/api/Monitor/WaitForBlock \
  -H 'Content-Type: application/json' \
  -d '{"poolNumber": 0, "timeoutMs": 30000}'

# 4. Smart contract: lista metodi del contratto target
curl -s -X POST $HOST/api/SmartContract/Get \
  -H 'Content-Type: application/json' \
  -d '{"address":"<base58 contract>"}'
# Estrarre byteCodeObjects, poi:
curl -s -X POST $HOST/api/SmartContract/Methods \
  -H 'Content-Type: application/json' \
  -d '{"byteCodeObjects":[{"name":"...","byteCode":"<base64>"}]}'

# 5. Diagnostic
curl -s -X POST $HOST/api/Diag/GetActiveNodes
curl -s -X POST $HOST/api/Diag/GetNodeInfo
curl -s -X POST $HOST/api/Diag/GetSupply
```

**Da osservare durante lo smoke**:

- nome esatto della RPC dei metodi: `gateway.py:smart_contract_methods` ha
  un fallback `client.SmartContractMethodsGet` → `client.getContractMethods`.
  Se il nodo espone un terzo nome, allineare il fallback;
- firma di `TokenHoldersGet`: `gateway.py:tokens_holders_get` prova
  `(token, offset, limit, order, desc)` e ricade su `(token, offset, limit, order)`
  se Thrift solleva `TypeError`. Verificare quale rami è attivo;
- struttura `Variant` per `TransactionResultGet`: il mapper in
  `services/monitor.py:_variant_to_python` cerca i campi `v_string`,
  `v_int`, `v_long`, `v_short`, `v_byte`, `v_bool`, `v_double`, `v_float`,
  `v_void`, `v_array`. Se la build del nodo usa nomi diversi, estendere
  la lista lì;
- shape esatta di `SupplyResult`: `services/diag.py:map_supply` cerca
  `initial`, `mined`, `currentSupply`/`current`. Confermare e, se necessario,
  aggiungere campi (es. `circulating`, `burned`).

---

## C. Builder Deploy/Execute — verifica `Transaction` reale

Il builder in `services/contracts.py` (`build_deploy_transaction`,
`build_execute_transaction`) presume che lo schema Thrift di `Transaction`
esponga questi campi: `id, source, target, amount, balance, currency, fee,
signature, userFields, smartContract` e — se presente — `type`. Allo stesso
modo `SmartContractInvocation` deve esporre `sourceCode, byteCodeObjects,
method, params, forgetNewState`.

**Da fare**:

1. Generare `gen-py` (sezione A.1) e ispezionare la classe `api.ttypes.Transaction`
   confermando i nomi dei campi.
2. Se il campo `type` è in realtà `transactionType` o un'enum diversa,
   adeguare `services/contracts.py:TT_SMART_DEPLOY` / `TT_SMART_EXECUTE`
   e i `setattr` corrispondenti.
3. Eseguire un Deploy reale di un contratto `AccessRights` minimal e
   verificare che il nodo lo sigilli correttamente.
4. Eseguire un Execute (`method=transfer`) sul contratto deployato.

---

## D. Sezione 5 del piano — Notifier SSE (non implementata)

Sezione marcata "opzionale, v2" nel piano. Non implementata in questa
sessione. Per chiudere:

1. Aggiungere `flask-sse` (o equivalente) a `requirements.txt`.
2. Implementare `routes/notifier.py` (oppure un blocco in `gateway.py`
   per coerenza con lo stile attuale) con endpoint
   `GET /Notifier/Stream/<address>`.
3. Worker thread che chiama `WaitForBlock` / `WaitForSmartTransaction`
   in loop e pubblica gli eventi su Redis pubsub; il fan-out SSE
   consuma il pubsub.
4. Throttling per indirizzo + chiusura idle dopo N minuti.
5. Test: client SSE che riceve almeno un evento `block` quando il
   nodo emette un nuovo pool.

---

## E. CI minima (Step 9 del piano)

Aggiungere `.github/workflows/ci.yml`:

```yaml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install -r requirements-dev.txt
      - run: pytest tests/ -v
      - run: python -m compileall gateway.py services
```

Non aggiunto in questa sessione per evitare di forzare workflow al primo
commit; abilitare quando il fork è in stato "ready for PR".

---

## F. PR upstream a `molaanaa/baba-node-api` (Step 10 del piano)

Lo scope MCP di questa sessione è limitato a `EnzinoBB/baba-node-api`,
quindi non posso aprire la PR cross-repo. Procedura:

1. Forkare `molaanaa/baba-node-api` sotto `EnzinoBB` (Step 1).
2. Aprire branch `feature/smart-contracts-and-metadata` sul fork.
3. Riportare i commit di questo branch (`Task 1` … `Task 5`) sul fork —
   eventualmente ristrutturando in `routes/` + `services/` come da Sezione 8
   del piano. La logica è già modulare (i `services/*` sono già pronti),
   resta solo da splittare gli endpoint da `gateway.py` in
   `routes/{smartcontract,tokens,userfields,diag,monitor}.py`.
4. Aprire PR upstream con descrizione dettagliata, citando per ciascun
   endpoint il riferimento al file `apihandler.cpp`/`hpp` del nodo che lo
   abilita (Sezione 11 del piano è già pronta).

---

## G. Endpoint esclusi dal piano (no-op intenzionali)

I metodi seguenti sono `NOT_IMPLEMENTED` lato nodo e quindi **non** vanno
esposti dal gateway, anche in futuro:

- `SmartMethodParamsGet` (`apihandler.cpp:2346`)
- `TransactionsStateGet`

Documentato qui per evitare che vengano riaperti per errore.

---

## H. Punti tecnici aperti minori

- **Wallet/key generation**: rimane fuori scope (non-custodial).
  Non aggiungere endpoint di firma server-side.
- **`smartContractResult` in TransactionFlow response**: il campo è
  passato attraverso ma non parsato. Quando il nodo restituisce un
  `SmartExecutionResult` strutturato, mappare i sotto-campi
  (`executionTime`, `ret_val` come Variant) usando
  `services/monitor.py:_variant_to_python`.
- **Rate limit dei wait helpers**: attualmente `2 per second; 60 per minute`.
  Se ArtVerse ha picchi di subscribers, valutare un limit per-IP più
  permissivo combinato con un cap globale concorrente (semaforo).
