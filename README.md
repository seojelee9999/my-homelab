# 홈랩 Ansible

메인 Kubernetes 클러스터는 Cilium으로 구성하고, 애플리케이션은 Argo CD로 배포한다.
클러스터 구축과 프로그램 설치, 운영 작업을 목적별 디렉터리로 나눠 관리한다.
모든 명령은 **저장소 루트**에서 실행하며, 대상 서버는 `inventory.ini`에서 관리한다.

## 디렉터리 구조

```text
.
├── ansible.cfg                 # Ansible 실행 설정
├── inventory.ini               # 서버 및 그룹
├── requirements.yml            # Ansible 컬렉션 의존성
├── playbooks/
│   ├── cluster/                # 메인 Kubernetes 클러스터 구축·초기화
│   │   ├── tasks/              # Cilium 클러스터 전용 공통 작업
│   │   ├── templates/          # kubeadm 및 Cilium 설정 템플릿
│   │   └── vars/               # 클러스터 버전·네트워크 설정
│   ├── apps/                   # 개별 프로그램 설치 및 앱 배포 준비
│   ├── operations/             # 노드 복구 및 인증정보 등록
│   ├── labs/                   # 별도 실습 환경
│   └── validation/             # 클러스터에서 실행하는 통신 검증
├── vault/                      # 배포용 Ansible Vault 인증정보 파일
├── docs/                       # 상세 구축·운영 안내
├── tests/                      # 로컬 자동화 테스트
├── collections/                # 로컬 Ansible 컬렉션
└── roles/                      # Ansible 역할 경로
```

## 클러스터 구축 — `playbooks/cluster/`

| 순서 | 플레이북 | 용도 |
| --- | --- | --- |
| 1 | [preflight_cilium.yml](playbooks/cluster/preflight_cilium.yml) | 노드와 네트워크 설정 사전 점검 |
| 2 | [reset_k8s.yml](playbooks/cluster/reset_k8s.yml) | 기존 클러스터를 재구축할 때 초기화 및 재부팅 |
| 3 | [bootstrap_cilium.yml](playbooks/cluster/bootstrap_cilium.yml) | Kubernetes, containerd, Cilium, Hubble 설치 |

신규 서버에서는 2번을 건너뛴다. 초기화 옵션, 설정과 실행 명령은
[Cilium 클러스터 구성 안내](docs/CILIUM_CLUSTER.md)를 따른다.
버전 및 네트워크 대역은 [cilium_cluster.yml](playbooks/cluster/vars/cilium_cluster.yml)에서 설정한다.

```bash
ansible-galaxy collection install -r requirements.yml
ansible-playbook playbooks/cluster/preflight_cilium.yml
# 신규 서버 또는 초기화를 완료한 노드에서 실행
ansible-playbook playbooks/cluster/bootstrap_cilium.yml
```

## 프로그램 설치·준비 — `playbooks/apps/`

| 플레이북 | 용도 |
| --- | --- |
| [helm.yml](playbooks/apps/helm.yml) | 후속 배포 플레이북이 사용하는 PATH의 Helm 설치 |
| [deploy_argocd.yml](playbooks/apps/deploy_argocd.yml) | Argo CD, GitHub 인증, 루트 Application 등록 |
| [ingress_controller.yml](playbooks/apps/ingress_controller.yml) | ingress-nginx 직접 설치 |
| [prepare_diet_gitops.yml](playbooks/apps/prepare_diet_gitops.yml) | Mealnote 로컬 PV와 Argo CD SSH 저장소 접근 준비 |

클러스터 구축 후 Helm, Argo CD 순서로 설치한다.

```bash
ansible-playbook playbooks/apps/helm.yml
ansible-playbook playbooks/apps/deploy_argocd.yml --ask-vault-pass
```

Cilium CNI 설치는 Ingress 컨트롤러 설치를 포함하지 않는다. Ingress를 Argo CD에서
관리하는 경우 직접 설치 플레이북과 중복 관리하지 않는다.
Mealnote 준비는 Argo CD와 저장소 접근 등 해당 플레이북의 선행조건을 갖춘 뒤 실행한다.

## 운영·복구 — `playbooks/operations/`

| 플레이북 | 용도 |
| --- | --- |
| [repair_root_rw.yml](playbooks/operations/repair_root_rw.yml) | 루트 파일시스템이 읽기 전용인 노드 복구 |
| [set_ghcr_secret.yaml](playbooks/operations/set_ghcr_secret.yaml) | Vault의 인증정보로 GHCR 이미지 pull Secret 등록 |
| [register-aws-credentials.yml](playbooks/operations/register-aws-credentials.yml) | 컨트롤 플레인에서 파일의 AWS 키로 ESO용 Secret 등록 ([사용법](docs/AWS_ESO_SECRET.md)) |

`vault/deploy-vault.yaml`과 `vault/ghcr-pat-vault.yaml`은 배포에 사용하는 인증정보 파일이다.
암호화한 파일을 사용하는 명령에는 `--ask-vault-pass` 또는 기존 Vault 설정을 사용한다.
AWS credentials 파일은 [사용법](docs/AWS_ESO_SECRET.md)에 따라 컨트롤 플레인에서 관리한다.

## 실습·검증

| 플레이북 | 용도 |
| --- | --- |
| [labs/prepare_cka.yml](playbooks/labs/prepare_cka.yml) | 별도 `cka_cluster`의 실습용 노드 준비 |
| [validation/test-ingress.yml](playbooks/validation/test-ingress.yml) | ingress-nginx 경로에 테스트 앱을 배포하여 HTTP 통신 확인 |

`playbooks/validation/`은 실제 클러스터에 테스트 리소스를 배포한다.
`tests/`는 로컬에서 가짜 kubectl과 테스트용 인증정보를 사용하는 자동화 테스트다.

```bash
python3 -m unittest discover -s tests -v
```

## 파일 추가 기준

- 클러스터 자체의 구축·초기화와 전용 task, template, vars는 `playbooks/cluster/`에 둔다.
- 개별 프로그램 설치와 앱별 배포 준비는 `playbooks/apps/`에 둔다.
- 기존 환경의 복구·인증정보 관리는 `playbooks/operations/`에 둔다.
- 실습 환경은 `playbooks/labs/`, 실제 클러스터 검증은 `playbooks/validation/`에 둔다.
- 상세 사용법은 `docs/`, 로컬 자동화 테스트는 `tests/`에 둔다.

기존 루트 플레이북은 위 경로로 이동했다. 실행 명령이나 외부 자동화에서 사용하는 경로도
`ansible-playbook playbooks/<분류>/<파일명>`으로 지정한다.
`requirements.yml`은 Ansible 컬렉션 의존성 파일이며 플레이북이 아니다.

## 정리한 이전 플레이북

| 삭제 파일 | 정리 이유 / 대체 경로 |
| --- | --- |
| `init_k8s.yml` | Kubernetes 1.30 노드 준비를 `playbooks/cluster/bootstrap_cilium.yml`로 대체 |
| `disable_swap.yml` | 메인 bootstrap과 CKA 준비에 swap 비활성화가 포함됨 |
| `register_diet_ghcr.yml` | GHCR Secret 등록을 `playbooks/operations/set_ghcr_secret.yaml`로 통일 |
| `bastion.yml` | 현재 인벤토리에 대상 `subnet-router`가 없음 |
| `ec2-tail.yml` | 현재 인벤토리에 대상 `ec2-nodes`가 없음 |

플레이북 파일 삭제는 서버에서 실행 중인 서비스나 Kubernetes 리소스를 삭제하지 않는다.
