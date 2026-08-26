<div align="center">

# 🗂️ Directerior

**Directory + Interior** — 연구 프로젝트의 디렉토리를 아름답게 정돈하세요.

*인테리어 : 플랜테리어 = 디렉토리 : **디렉테리어***

[English](README.md) | **한국어** | [中文](README.zh.md)

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)
![Dependencies](https://img.shields.io/badge/Dependencies-zero-orange)
[![CI](https://github.com/HSoo-Kim/directerior/actions/workflows/ci.yml/badge.svg)](https://github.com/HSoo-Kim/directerior/actions/workflows/ci.yml)

</div>

---

## 먼저 Agent Skill, 그 아래 안전 CLI

Directerior는 Claude Code 같은 에이전트에게 설치하는 **Agent Skill**입니다.
에이전트가 [SKILL.md](SKILL.md)를 읽어 구조를 설계·매핑하고 사용자 승인을
받은 뒤, 내장된 무의존성 Python CLI를 안전 실행 엔진으로 사용합니다.

| 에이전트 | 설치 위치 |
|---|---|
| Claude Code (사용자 전역) | `~/.claude/skills/directerior/` |
| Claude Code (프로젝트) | `<project>/.claude/skills/directerior/` |
| 범용 skill 에이전트 | `~/.agents/skills/directerior/` |

보통 CLI를 외울 필요 없이 AI에게 아래처럼 요청하면 됩니다.

## AI에게 이렇게 요청하세요

**새 연구 프로젝트**

> Directerior 스킬로 이 프로젝트를 시작해줘. 적합한 위계 후보 2~3개를 먼저
> 보여주고 내가 선택하면 번호가 붙은 plan/code/results 구조를 만들어줘.
> 데이터 재배치 전에는 반드시 승인을 요청해.

**기존 코드베이스의 산출물만 정리**

> 코드는 지금 위치 그대로 둘 거야. Directerior는 큰 산출물 디렉토리에만 써줘.
> 임계값을 넘은 것들을 보여주고, 하드코딩된 경로가 계속 동작하도록 `--link`를
> 쓰고, 옮기기 전에 반드시 물어봐.

**기존 `code/results` 구조 변환**

> Directerior `migrate-layout --dry-run`으로 모든 변경 경로와 undo 방법을
> 먼저 보여줘. 승인받은 뒤에만 변환해.

**마이그레이션 되돌리기·재적용**

> Directerior history를 보여주고 파일 변경 여부를 검증해. 최신 마이그레이션을
> 엄격히 undo하기 전에 승인을 요청하고, 나중에 요청하면 다시 검증 후 redo해.

**대용량 결과 HDD 이동**

> Directerior로 100MB 초과 결과와 HDD 여유 공간을 보여줘. 어떤 실험을
> offload할지 물어보고 승인 전에는 삭제하거나 이동하지 마.

연구 프로젝트는 실험을 낳고, 실험은 잡동사니를 낳습니다. 결과물이 코드 옆에
쌓이고, 방법론마다 폴더 모양이 제각각이 되고, SSD는 40GB짜리 체크포인트로
조용히 가득 찹니다 — AI 코딩 에이전트는 그 속도를 더 높일 뿐입니다.

**Directerior**는 가벼운 실험 디렉토리 매니저입니다:

- 🚧 **디렉토리만 건드리고 코드는 절대 안 건드림** — import 재작성도, 경로
  문자열 치환도, `AGENTS.md` 수정도 없음. 참조가 깨질 이동은 조용히 "고치는"
  대신 **목록으로 보고하고 거부**
- 📁 **하나의 레이아웃** — 방법론별·실험별로 `code/`와 `results/` 분리
- 🧭 **위계는 당신의 선택** — 기본 `methods/experiments`, 또는 원하는 깊이로:
  `datasets/methods/experiments`, `phases/trials`, …
- ⚖️ **용량 감시** — `results/`를 임계값(기본 **100MB**)과 비교해 오프로드
  후보를 전용 종료 코드로 알림
- 💾 **HDD 오프로드** — 큰 결과물을 보조 드라이브로 옮기고 **junction/symlink**를
  남겨 모든 코드 경로가 그대로 동작
- 🙋 **승인 우선** — 원본을 삭제하거나 데이터를 재배치하는 명령은 `--yes` 없이 무조건 실패;
  에이전트는 반드시 먼저 물어봐야 함
- 🛡️ **검증된 전송** — 복사 → SHA-256 트리 검증 → 원본 삭제;
  전송 전 저장 공간도 확인
- ↩️ **되돌릴 수 있음** — `adopt`와 `rm`은 원장에 기록되고, `rm`은 삭제 대신
  HDD 휴지통으로 이동; 나머지는 git이 지킴
- 🧹 **자가 정리** — 깨진 링크 복구, 고아 데이터 보고, 빈 디렉토리 정리;
  **데이터는 절대 자동 삭제하지 않음**
- 🪶 **런타임 의존성 제로** — 작은 Python CLI, DB 없음, DVC 없음

## 새 프로젝트에 쓰기를 권장합니다

Directerior는 **처음부터 이 레이아웃 위에서 시작하는 프로젝트**를 위한
도구이며, 이미 실제 소스 트리가 있는 디렉토리에서는 `init`이 거부합니다
(`--allow-existing`으로 강행 가능). 이유는 단순합니다. 디렉토리를 옮기는 데는
1밀리초면 되지만, 그 이동에 맞춰 모든 import·하드코딩 경로·설정 파일·노트북·
셸 스크립트를 동기화하는 일은 끝이 없는 코드 수정 문제이고, 이 도구는 코드를
수정하지 않기로 **의도적으로** 선택했기 때문입니다.

이미 성숙한 리포지토리가 있다면 코드는 그대로 두고 산출물만 관리하세요:

```bash
python scripts/expman.py adopt ./outputs my-method exp01 --link --yes
python scripts/expman.py offload my-method exp01 --yes
```

## 동작 방식

```
project/                        # 루트 = .expman.json 위치
├── .expman.json                # { "hdd_root": "D:/exp-archive", "threshold_mb": 100 }
└── methods/
    └── lora-finetune/          # 방법론 하나
        └── experiments/
            └── exp01-baseline/ # 실험(런/변형) 하나
                ├── 1_plan/         # 목표·가설·프로토콜·결정
                ├── 2_code/         # 이 실험 전용 스크립트·설정
                ├── 3_results/      # 모든 산출물은 여기로
                └── manifest.json
```

`results/`가 임계값을 넘고 사용자가 오프로드를 승인하면:

```
 SSD (빠름, 작음)                           HDD (큼, 여유)
 methods/.../exp01/results  ──junction──▶   exp-archive/project/methods/.../exp01/results
        ▲
        └─ 코드는 이 경로를 그대로 읽고 씀 — 아무것도 깨지지 않음
```

Windows에서 junction은 **관리자 권한 불필요**, POSIX에서는 symlink 사용.

## 빠른 시작

```bash
cd my-project
python scripts/expman.py init --hdd-root D:/exp-archive --threshold-mb 100
python scripts/expman.py new lora-finetune exp01-baseline -d "baseline"

# ... 실험 실행, 산출물은 results/에 저장 ...

python scripts/expman.py scan                  # exit 2 = 오프로드 후보 존재
python scripts/expman.py offload lora-finetune exp01-baseline --yes
python scripts/expman.py status
```

## 사용자 정의 위계

2단(`methods` → `experiments`)은 기본값일 뿐 한계가 아닙니다 — init에서
원하는 위계를 정의하세요:

```bash
python scripts/expman.py init --hdd-root D:/exp-archive --hierarchy datasets,methods,experiments
# datasets/<데이터셋>/methods/<방법론>/experiments/<실험>/{code,results}
```

이후 모든 명령은 레벨당 이름 하나씩을 순서대로 받습니다:

```bash
python scripts/expman.py new imagenet lora-finetune exp01-baseline
python scripts/expman.py offload imagenet lora-finetune exp01-baseline --yes
```

위계는 `.expman.json`에 저장됩니다. init 때 한 번 정하세요 — 데이터가 쌓인
뒤 바꾸려면 디렉토리를 수동으로 마이그레이션해야 합니다.

## 명령어

| 명령 | 용도 |
|---|---|
| `init --hdd-root PATH [--threshold-mb N] [--hierarchy a,b,c] [--allow-existing]` | 프로젝트 루트에서 1회 설정 |
| `new <이름...> [-d DESC]` | 번호가 붙은 plan/code/results 스캐폴드 |
| `add <부모> <slug> [--group N] [--file]` | 다음 `N_slug` 또는 `N_a_slug` 생성 |
| `scan [--json]` | 임계값 초과 로컬 `results/` 목록 (있으면 exit 2) |
| `offload <이름...> --yes` | `results/`를 HDD로 이동 후 링크백 |
| `restore <이름...> --yes` | 검증 복사 후 승인된 HDD 원본 삭제 |
| `rename <기존...> --to <새이름...> --yes` | 로컬 leaf와 HDD 미러 동시 변경 |
| `rm <이름...> --yes [--purge]` | 로컬 leaf와 HDD 복사본을 HDD 휴지통으로 이동; `--purge`는 영구 삭제 |
| `adopt <path> <이름...> [--as NAME] [--link] [--allow-breaking-refs] --yes` | 제자리를 벗어난 산출물 편입; `--link`는 원래 경로 유지 |
| `clean [--fix]` | HDD 빈 디렉토리 정리, 깨진 링크 복구, 고아·휴지통 보고 |
| `migrate-layout [--dry-run] --yes` | 변경 미리보기 또는 번호 구조 변환 |
| `history [--json]` | 가역 작업 기록 표시(마이그레이션, `adopt`, `rm`) |
| `undo [ID|latest] --yes` | 마이그레이션·`adopt`·`rm`을 엄격 검증 후 되돌림 |
| `redo [ID|latest] --yes` | undo한 마이그레이션 재적용 |
| `status [--json]` | 실험별 바이트와 local/HDD 위치 |

데이터를 재배치하는 모든 명령은 `--allow-dirty`도 받습니다(아래 참고).

## 예상 밖 경로 처리

도구들은 하드코딩 경로를 좋아합니다(`./outputs/`, `./wandb/`, `~/runs/`).
산출물이 레이아웃 밖에 생기면 [SKILL.md](SKILL.md)의 에이전트 계약에 따라
조용히 옮기는 대신 **반드시 사용자에게 번호 선택지**(편입, 편입+링크백,
`_shared` 방법론, 그대로 두기, 직접 경로 입력)를 제시하고 묻습니다.

고집 센 도구에는 `adopt --link`: 산출물은 `results/`로 이동하고, 원래 경로에
junction이 남아 도구는 계속 동작합니다.

## 참조 차단기

`--link` 없이 실행한 `adopt`는 옮길 경로를 참조하는 텍스트를 프로젝트 전체에서
먼저 검색합니다. 코드 섹션이면 `import <모듈>` 형태도 함께 봅니다. 하나라도
걸리면 이동을 중단하고 무엇이 깨질지 정확히 출력합니다:

```text
ERROR: moving /home/me/proj/outputs would break 2 reference(s):
  train.py:14: OUT = "outputs/checkpoints"
  AGENTS.md:52: outputs/ holds every checkpoint
  directerior does not rewrite code, configs, or docs.
  Use --link to keep the original path working, fix the references yourself,
  or pass --allow-breaking-refs to move anyway.
```

보고할 뿐 고치지는 않습니다. import와 경로 문자열을 자동으로 바꾸는 일은 실패가
조용한 코드모드입니다 — 틀린 경로는 예외를 내지 않고 그냥 빈 결과를 만듭니다.
그래서 그 판단은 사용자 몫으로 남깁니다.

## 트랜잭션 경계로서의 git

git 저장소 안에서는 **추적 중인** 파일이 수정된 상태이면 재배치 명령이 실행을
거부합니다. `git reset --hard`가 언제나 유효한 탈출구로 남아야 하기 때문입니다.
추적되지 않는 파일(결과물, 체크포인트)은 어차피 git이 복구해주지 못하므로 막지
않고, 대신 작업 원장이 책임집니다. `--allow-dirty`로 무시할 수 있습니다.

## 새 프로젝트와 기존 프로젝트

새 프로젝트는 `1_plan/`, `2_code/`, `3_results/`를 자동 생성합니다.
기존 Directerior 프로젝트는 `migrate-layout --yes`로 변환합니다. 임의의 기존
코드베이스는 설계상 범위 밖입니다 —
[새 프로젝트에 쓰기를 권장합니다](#새-프로젝트에-쓰기를-권장합니다) 참고.

기본은 `1_baseline`, `2_training`처럼 숫자만 사용합니다. 같은 1번 단계에
병렬 분기가 생길 때만 `1_a_baseline`, `1_b_augmented`로 확장합니다.
`add`가 다음 prefix를 자동 계산합니다.

## 엄격한 가역 작업

원장은 프로젝트 밖 사용자 상태 디렉토리에 저장되어, 복원된 프로젝트 안에는
기록 파일이 남지 않습니다. `history` 하나에 두 종류가 함께 들어갑니다:

| 종류 | 명령 | 검증 | 되돌리기 |
|---|---|---|---|
| migration | `migrate-layout` | SHA-256 내용 전체 | `undo` + `redo` |
| path operation | `adopt`, `rm` | 경로·크기 구조 | `undo` (재적용은 명령 재실행) |

`rm`은 실험과 HDD 사본을 삭제하는 대신
`<hdd_root>/.trash/<프로젝트>/<작업-id>/`로 옮기고, `undo`가 오프로드 링크까지
포함해 원래 자리로 되돌립니다. 데이터를 실제로 파괴하는 명령은 `--purge`뿐입니다.

undo 전후로
`.expman.json` 원본 바이트, 모든 변경 파일의 경로·크기·SHA-256, 빈 디렉토리,
HDD 위치와 junction 상태를 검증합니다. 하나라도 달라졌으면 이동 전에 거부합니다.
성공한 undo는 기존 이름·파일 바이트·설정 포맷·HDD 경로·링크를 그대로 복구하고,
외부 원장만 남겨 redo를 가능하게 합니다.

schema v2 원장은 미래 version graph의 edge이기도 합니다:

```text
parent_id -> operation_id
before_fingerprint -> after_fingerprint
operation_type = migrate_layout
```

fingerprint는 명령 문자열이 아니라 프로젝트 상태를 나타내므로, 향후 rename,
offload 같은 작업도 앞 작업의 결과와 다음 작업의 입력 상태가 같으면 같은 graph에
연결할 수 있습니다. 기존 schema v1 원장도 로드 시 fingerprint를 계산해 호환합니다.

## 팀에서 쓰기

`.expman.json`을 커밋해 레이아웃과 임계값을 공유하세요. 드라이브 위치는
각자 환경 변수로 덮어씁니다:

```bash
set EXPMAN_HDD_ROOT=E:\my-archive      # Windows
export EXPMAN_HDD_ROOT=/mnt/archive    # POSIX
```

오프로드 데이터는 `<hdd_root>/<프로젝트명>/…` 아래에 저장되므로 아카이브
드라이브 하나로 여러 프로젝트를 충돌 없이 관리할 수 있습니다.

## 안전 불변식

- `offload`, `restore`, `rename`, `rm`, `adopt`, `migrate-layout`, `undo`,
  `redo`는 **`--yes` 없이
  무조건 실패** — 원본 삭제/재배치는 사용자 승인 필수
- offload/restore는 복사 → SHA-256 전체 트리 검증 → 원본 삭제 순서;
  공간 부족이면 복사 전에 중단
- **소스 코드는 절대 재작성하지 않음** — 깨질 참조는 보고·거부하고 판단은 사용자에게
- **에이전트 지시 파일**(`AGENTS.md`, `CLAUDE.md`, `.claude/`, …)은 이동·삭제 대상에서 거부
- 추적 파일이 수정된 git 워킹트리에서는 `--allow-dirty` 없이 재배치 불가
- `rm`은 HDD 휴지통을 통해 되돌릴 수 있고, 데이터를 실제로 지우는 건 `--purge`뿐
- 조용한 덮어쓰기 없음 — 대상이 이미 있으면 항상 거부
- `restore` / `clean --fix`는 링크와 빈 디렉토리만 제거, 데이터는 건드리지 않음
- 고아가 된 HDD 데이터는 **보고만 하고 절대 자동 삭제하지 않음**

## 라이선스

[MIT](LICENSE) © HSoo-Kim
