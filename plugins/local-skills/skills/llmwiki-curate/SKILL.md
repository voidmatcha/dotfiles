---
name: llmwiki-curate
description: "Curate the llmwiki vault: turn session history into '실패한 시도' lessons, and turn dropped raw material into Library notes. Use when the user asks to 실패한 시도 정리, 교훈 뽑기, 볼트 정리, library 정리, raw 던진거 위키화, llmwiki 큐레이션, curate the wiki, or write up lessons learned. Not for reading session history (use llmwiki search/sessions) or for llmwiki code changes."
---

# llmwiki 큐레이션

볼트에서 기계가 못 하는 두 가지를 한다. 실패한 시도를 교훈으로 적는 것,
가져온 자료를 위키 노트로 만드는 것. 나머지(수집, 컴파일, 스냅샷)는
launchd 가 매일 04:00 에 알아서 한다.

**경계**: CLI 는 후보를 세우고 파일을 쓴다. 판단과 문장은 전부 네 몫이다.
후보 목록을 그대로 승인하지 마라. 키워드는 재현율만 맞춘 것이라 오탐이 많다.

체크아웃을 먼저 잡는다. 호출자의 cwd 를 믿지 마라.

```bash
DOTFILES_DIR="${DOTFILES_DIR:-$(
  for l in "$HOME/.zshrc" "$HOME/.agent/AGENTS.md" "$HOME/.claude/settings.json"; do
    t=$(readlink "$l" 2>/dev/null) || continue
    r=$(cd "$(dirname "$t")/.." 2>/dev/null && pwd) || continue
    [ -d "$r/scripts" ] && printf '%s' "$r" && break
  done
)}"
cd "$DOTFILES_DIR" && python3 -m scripts.llmwiki status
```

## A. 실패한 시도 채우기

1. 후보를 받는다. 기본은 최근 30일, 노트 있는 프로젝트만.

   ```bash
   python3 -m scripts.llmwiki lessons list --limit 10
   python3 -m scripts.llmwiki lessons list --project llmwiki --days 90
   ```

2. **각 후보를 읽고 판정한다.** 통과 기준은 하나다.
   *다음에 같은 상황에서 다르게 행동하게 만드는가?*

   | 판정 | 예시 |
   |---|---|
   | 승인 | 내가 뭘 깨뜨렸고, 왜 그랬고, 뭘 대신 했어야 하는가 |
   | 기각 | 남의 버그를 고친 작업, 정상적인 테스트 실패, 단순 진행 보고 |

   점수는 순위용 눈금일 뿐이다. 긴 요약일수록 높게 나오는 길이 편향이 있다.
   점수가 아니라 본문을 읽고 정해라.

3. 승인은 **교훈 문장을 네가 써서** 넣는다. 세션 요약을 복사하지 마라.
   요약은 "무엇을 했나"고 교훈은 "다시 하지 말 것"이다.

   ```bash
   python3 -m scripts.llmwiki lessons accept <ref> --text "..."
   python3 -m scripts.llmwiki lessons dismiss <ref> --reason "남의 버그 수정"
   ```

   좋은 문장의 조건:
   - 금지형 또는 명령형으로 시작 (`~하지 말 것`, `~할 것`)
   - 무엇이 망가졌는지 구체적으로
   - 대신 무엇을 해야 하는지까지

   ```
   나쁨: 설정 파일 수정 중 문제가 발생했다
   좋음: JSON 을 문자열 치환으로 고치지 말 것. 파싱해서 고칠 것.
         라이브 claude-settings.json 을 정규식으로 건드려 훅 10개를 날렸다.
   ```

4. 승인도 기각도 `lessons.ndjson` 에 남아 다시 제안되지 않는다. 되돌리려면
   그 파일에서 해당 줄을 지운다.

## B. Library 채우기

`raw/` 는 던지는 곳, `library/` 는 위키 노트다. 원본은 지우지 않는다.

1. 새로 던져진 자료로 빈 노트를 세운다. 같은 내용은 이름이 달라도 한 번만
   들어간다(sha 비교).

   ```bash
   python3 -m scripts.llmwiki library ingest
   python3 -m scripts.llmwiki library pending
   ```

2. **원본을 읽고** 노트의 세 절을 채운다. `<!-- GEN:source -->` 안쪽은
   건드리지 마라. 다음 ingest 가 덮어쓴다.

   - `## 요약` — 원문의 주장. 구조가 있으면 표로. 수치는 원문 그대로.
   - `## 왜 담았나` — 이걸 왜 우리 맥락에 넣었나. 여기가 이 노트의 값이다.
     원문 요약만 있으면 남의 글 사본에 지나지 않는다.
   - `## 연결` — `[[projects/…]]`, `[[library/…]]` 위키링크. 우리 볼트에는
     프로젝트 노트 간 링크가 아직 0개다. 여기서 만드는 링크가 그 시작이다.

3. 요약을 채운 뒤에만 done 이 통과한다. 빈 노트는 거부된다.

   ```bash
   python3 -m scripts.llmwiki library done <slug>
   ```

4. `ingest` 가 `changed` 를 돌려주면 **원본이 수정된 것**이다. 노트를 새로
   만들지 않고 알리기만 한다. 바뀐 부분을 확인하고 요약을 손본 뒤 resync 한다.
   요약은 지워지지 않고 status 만 pending 으로 내려간다.

   ```bash
   python3 -m scripts.llmwiki library resync <slug>
   ```

## URL 자료

`raw/` 는 파일만 받는다. URL 은 먼저 로컬로 받아서 던진다.

- 공개 페이지: `defuddle <url> --md > "$VAULT/raw/$(date +%F)-<이름>.md"`
- 로그인 필요 또는 민감: `agent-browser` 로 연다.
  LinkedIn·X 등은 비로그인 페처가 403 을 준다.
- **금지**: 내부·민감 URL 을 Jina/Exa 같은 호스티드 서비스로 보내지 마라.
  플랫폼 대량 수집도 하지 마라(계정 제재).

## 붙여넣은 글의 출처 찾기

사용자가 링크 없이 본문만 붙여넣는 경우가 많다. 출처는 **찾아보되 추정하지
마라.** 틀린 출처는 없는 출처보다 나쁘다.

1. 본문에서 **고유한 한 문장**을 고른다. 흔한 문장은 쓸모없다. 고유명사,
   수치, 특이한 표현이 들어간 줄이 좋다.
2. 그 문장을 따옴표로 묶어 검색한다. 한 번에 한두 질의만. 대량 조회 금지.
3. 결과를 **검증한다.** 찾은 페이지를 실제로 열어 그 문장이 있는지 확인한다.
   제목만 비슷한 것은 출처가 아니다.
4. 확인됐을 때만 기록한다.

   ```bash
   python3 -m scripts.llmwiki library set-origin <slug> "https://..."
   ```

5. 못 찾으면 `origin` 을 비워두고 노트 본문에 어떻게 들어왔는지 적어라.
   예: "사용자가 세션에 직접 붙여넣음, 2026-08. 원문 링크 미확인."

**안 되는 경우가 많다는 것을 알고 하라.** 로그인 담장 뒤의 글(LinkedIn,
비공개 Slack, 사내 위키)은 검색엔진에 없다. 이때는 4번을 건너뛰고 5번으로
간다. 사용자에게 링크를 물어보는 것이 추정보다 낫다.

**금지**: 내부·민감 URL 이나 그 본문 조각을 Jina/Exa 같은 호스티드 서비스로
보내지 마라. 사내 문서의 문장을 검색창에 넣는 것도 유출이다. 공개 글로
확신할 때만 검색한다.

## 하지 말 것

- 후보를 일괄 승인하지 마라. 한 건씩 읽고 판정한다.
- 세션 요약을 교훈으로 복사하지 마라. 교훈은 새로 쓰는 문장이다.
- GEN 마커 안에 손으로 쓰지 마라. 다음 compile 이 지운다.
- `raw/` 원본을 지우지 마라. 요약이 틀렸을 때 되짚을 근거다.
- 검증 안 된 자료를 Library 에 넣지 마라. 양이 아니라 관리가 위키를 살린다.
