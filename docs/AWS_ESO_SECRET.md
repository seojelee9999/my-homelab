# 컨트롤 플레인에서 ESO용 AWS Secret 등록

`playbooks/operations/register-aws-credentials.yml`은 Ansible 실행 머신에서 호출하고,
`inventory.ini`의 **`kube_control_plane[0]` 호스트에서 작업**한다.
컨트롤 플레인의 AWS access key와 secret access key를 Kubernetes Secret으로
등록하여 ESO(External Secrets Operator)가 AWS SSM Parameter Store 인증에 사용하도록 한다.
동일한 키로 재실행하면 변경하지 않는다.

| 항목 | 기본값 |
| --- | --- |
| AWS 파일 | 컨트롤 플레인의 `/home/<ansible_user>/.aws/credentials` (현재 `/home/ubuntu/.aws/credentials`) |
| AWS 프로필 | `homelab-eso` |
| kubeconfig | 컨트롤 플레인의 `/etc/kubernetes/admin.conf` |
| Namespace | `external-secrets` |
| Secret | `aws-ssm-credentials` |
| Secret 필드 | `access-key-id`, `secret-access-key` |

## 1. 실행 환경

Ansible 실행 머신에 이 저장소와 `ansible-core`가 필요하다.
컨트롤 플레인에는 Python 3와 `kubectl`이 필요하며, 인벤토리의 SSH 사용자로
접속한 뒤 `become: true`로 작업한다. 추가 Ansible collection이나 Kubernetes
Python 패키지는 필요 없다.

`external-secrets` namespace는 ESO 설치 시 먼저 생성되어 있어야 한다.
kubeconfig에는 해당 namespace의 Secret 조회 및 생성·패치 권한이 필요하다.

## 2. AWS 키 파일 준비

아래 명령은 **컨트롤 플레인에서** 실행한다. 기존 파일과 프로필은 보존한다.

```bash
mkdir -p "$HOME/.aws"
chmod 700 "$HOME/.aws"
touch "$HOME/.aws/credentials"
chmod 600 "$HOME/.aws/credentials"
vi "$HOME/.aws/credentials"
```

편집기에서 다음 섹션을 추가하고 예시 문자열을 실제 키로 바꾼다.
실제 키는 Git 파일이나 셸 명령행에 입력하지 않는다.

```ini
[homelab-eso]
aws_access_key_id = REPLACE_WITH_ACCESS_KEY_ID
aws_secret_access_key = REPLACE_WITH_SECRET_ACCESS_KEY
```

IAM 사용자의 액세스 키를 사용한다. 만료되는 STS/SSO 키와 세션 토큰은 이
구성에서 지원하지 않는다. AWS 키 환경변수는 읽지 않는다.

## 3. 검토 후 등록

**Ansible 실행 머신**의 저장소 루트에서 실행한다. `--check`는 입력 파일과 현재 Secret을 조회해
변경 필요 여부만 확인하며, 실제 AWS 인증이나 SSM 권한을 검증하지는 않는다.

```bash
ansible-playbook -i inventory.ini playbooks/operations/register-aws-credentials.yml --check
ansible-playbook -i inventory.ini playbooks/operations/register-aws-credentials.yml
```

경로와 프로필은 비밀값이 없는 인자로 변경할 수 있다.

```bash
ansible-playbook -i inventory.ini playbooks/operations/register-aws-credentials.yml \
  -e aws_credentials_file=/home/ubuntu/.aws/credentials \
  -e aws_profile=homelab-eso \
  -e kubeconfig_file=/etc/kubernetes/admin.conf
```

두 파일 경로는 모두 **컨트롤 플레인 기준의 절대 경로**로 지정한다.
기본 AWS 파일 경로는 SSH 사용자 기준이고, 파일 읽기와 Secret 등록은 sudo로 수행한다.

사전 검사는 키 값 존재 여부와 세션 자격 증명 사용 여부만 확인한다.
파일 읽기 실패, namespace 부재, API 접근 오류는 실제 작업 단계에서 실패 처리한다.

비밀값을 다루는 task는 `no_log: true`, 적용 task는 `diff: false`로 처리한다.
Secret은 메모리에서 구성해 kubectl의 stdin으로 전달한다. 평문 Secret YAML
파일을 생성하지 않으며 비밀값을 kubectl 명령행 인자로 전달하지 않는다.
Ansible 디버그 모드(`ANSIBLE_DEBUG`)는 사용하지 않는다.

## 4. 등록 확인 및 키 교체

컨트롤 플레인에서 확인한다.

```bash
sudo kubectl --kubeconfig /etc/kubernetes/admin.conf -n external-secrets get secret aws-ssm-credentials
```

키를 교체할 때는 credentials 파일을 수정하고 같은 플레이북을 다시 실행한다.
ESO의 SSM 조회가 정상인 것을 확인한 뒤 이전 AWS 키를 폐기한다.
생성한 Kubernetes Secret은 ESO가 계속 참조하므로 유지한다. 원본 파일도
재실행을 위해 권한을 제한해 보관하거나, 필요할 때 별도 보관소에서 복원한다.

이 플레이북은 AWS 키 Secret 등록만 수행한다. `ClusterSecretStore` 또는
`SecretStore`에는 위 Secret 이름·필드 이름을 지정하고, `ClusterSecretStore`인
경우 참조 namespace도 `external-secrets`로 지정해야 한다. SSM 파라미터를 가져올
`ExternalSecret`, SecretStore의 AWS `ParameterStore` 설정 및 SSM 파라미터는
별도로 준비한다. 이 플레이북은 IAM 권한이나 ESO 리소스를 생성하지 않는다.

Git에 기록하는 것은 플레이북과 이 문서다. 실제 credentials 파일이나
Secret의 `-o yaml` 출력은 Git에 보관하지 않는다.

참고: [command stdin](https://docs.ansible.com/projects/ansible/latest/collections/ansible/builtin/command_module.html).
