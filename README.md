# 홈랩 Ansible

메인 Kubernetes 클러스터는 Cilium으로 구성하고, 애플리케이션은 Argo CD로 배포한다.
실행 대상은 `inventory.ini`에서 관리한다.

## 메인 클러스터 구성

| 순서 | 플레이북 | 용도 |
| --- | --- | --- |
| 1 | `preflight_cilium.yml` | 노드와 네트워크 설정 사전 점검 |
| 2 | `reset_k8s.yml` | 기존 클러스터를 재구축할 때 초기화 및 재부팅 |
| 3 | `bootstrap_cilium.yml` | Kubernetes, containerd, Cilium, Hubble 설치 |
| 4 | `helm.yml` | 후속 배포 플레이북이 사용하는 PATH의 Helm 설치 |
| 5 | `deploy_argocd.yml` | Argo CD, GitHub 인증, 루트 Application 등록 |

신규 서버에서는 2번을 건너뛴다. 초기화 옵션, 설정과 실행 명령은
[Cilium 클러스터 구성 안내](CILIUM_CLUSTER.md)를 따른다.
버전 및 네트워크 대역은 `vars/cilium_cluster.yml`에서 설정한다.

## 필요할 때 실행하는 플레이북

| 플레이북 | 용도 |
| --- | --- |
| `prepare_diet_gitops.yml` | Mealnote 로컬 PV와 Argo CD SSH 저장소 접근 준비 |
| `set_ghcr_secret.yaml` | Vault의 인증정보로 GHCR 이미지 pull Secret 등록 |
| `prepare_cka.yml` | 별도 `cka_cluster`의 실습용 노드 준비 |
| `repair_root_rw.yml` | 루트 파일시스템이 읽기 전용인 노드 복구 |
| `ingress_controller.yml` | ingress-nginx를 직접 설치할 때 사용 |
| `test-ingress.yml` | ingress-nginx 경로에 테스트 앱을 배포하여 HTTP 통신 확인 |

Cilium CNI 설치는 Ingress 컨트롤러 설치를 포함하지 않는다. Ingress를 Argo CD에서
관리하는 경우 직접 설치 플레이북과 중복 관리하지 않는다.

`deploy-vault.yaml`과 `ghcr-pat-vault.yaml`은 배포에 사용하는 인증정보 파일이다.
암호화한 파일을 사용하는 명령에는 `--ask-vault-pass` 또는 기존 Vault 설정을 사용한다.
`requirements.yml`은 Ansible 컬렉션 의존성 파일이며 플레이북이 아니다.

## 정리한 이전 플레이북

| 삭제 파일 | 정리 이유 / 대체 경로 |
| --- | --- |
| `init_k8s.yml` | Kubernetes 1.30 노드 준비를 `bootstrap_cilium.yml`로 대체 |
| `disable_swap.yml` | 메인 bootstrap과 CKA 준비에 swap 비활성화가 포함됨 |
| `register_diet_ghcr.yml` | GHCR Secret 등록을 `set_ghcr_secret.yaml`로 통일 |
| `bastion.yml` | 현재 인벤토리에 대상 `subnet-router`가 없음 |
| `ec2-tail.yml` | 현재 인벤토리에 대상 `ec2-nodes`가 없음 |

플레이북 파일 삭제는 서버에서 실행 중인 서비스나 Kubernetes 리소스를 삭제하지 않는다.
