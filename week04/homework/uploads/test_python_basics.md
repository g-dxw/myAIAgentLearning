# Python 编程基础知识

## 1. 数据类型

Python 是一种动态类型语言，内置了多种数据类型。

### 1.1 基本数据类型

- **int（整数）**：Python 3 中整数没有大小限制。例如：`42`, `-7`, `0`
- **float（浮点数）**：双精度浮点数。例如：`3.14`, `-0.001`, `2.0e3`
- **str（字符串）**：Unicode 字符串，不可变类型。例如：`"hello"`, `'Python'`
- **bool（布尔）**：只有 `True` 和 `False` 两个值。
- **NoneType**：只有一个值 `None`，表示空值。

### 1.2 容器类型

- **list（列表）**：有序可变序列。创建方式：`[1, 2, 3]`
- **tuple（元组）**：有序不可变序列。创建方式：`(1, 2, 3)`
- **dict（字典）**：键值对集合。创建方式：`{"name": "Alice", "age": 25}`
- **set（集合）**：无序不重复元素集。创建方式：`{1, 2, 3}`

### 1.3 类型转换

Python 提供了内置的类型转换函数：
- `int()`：将值转为整数
- `float()`：将值转为浮点数
- `str()`：将值转为字符串
- `bool()`：将值转为布尔值
- `list()`：将可迭代对象转为列表

示例代码：
```python
x = "42"
y = int(x)  # y 现在是整数 42
z = float(x)  # z 现在是浮点数 42.0
```

## 2. 函数定义

Python 使用 `def` 关键字定义函数。函数是一等公民，可以作为参数传递，也可以作为返回值。

### 2.1 基本函数

```python
def greet(name):
    return f"Hello, {name}!"

result = greet("World")  # 返回 "Hello, World!"
```

### 2.2 默认参数

```python
def power(base, exp=2):
    return base ** exp

power(3)      # 返回 9
power(3, 3)   # 返回 27
```

### 2.3 可变参数

使用 `*args` 接收任意数量的位置参数，`**kwargs` 接收任意数量的关键字参数：

```python
def summarize(*args, **kwargs):
    print(f"位置参数: {args}")
    print(f"关键字参数: {kwargs}")

summarize(1, 2, 3, name="Alice", age=25)
```

### 2.4 Lambda 表达式

Lambda 是匿名函数的简写方式：

```python
square = lambda x: x ** 2
numbers = [1, 2, 3, 4, 5]
squared = list(map(lambda x: x ** 2, numbers))  # [1, 4, 9, 16, 25]
```

## 3. 面向对象编程

Python 支持面向对象编程（OOP），核心概念包括类、继承、封装和多态。

### 3.1 类的定义

```python
class Animal:
    def __init__(self, name, sound):
        self.name = name
        self.sound = sound

    def speak(self):
        return f"{self.name} says {self.sound}"

class Dog(Animal):
    def __init__(self, name, breed):
        super().__init__(name, "Woof")
        self.breed = breed

    def fetch(self, item):
        return f"{self.name} fetches the {item}"
```

### 3.2 特殊方法（魔术方法）

Python 类可以定义特殊方法来实现运算符重载和内置行为：
- `__init__`：构造函数
- `__str__`：字符串表示（`str()` 调用）
- `__repr__`：官方字符串表示
- `__len__`：`len()` 调用
- `__getitem__`：索引访问 `obj[key]`
- `__eq__`：等于运算符 `==`

### 3.3 类方法和静态方法

```python
class Counter:
    count = 0

    @classmethod
    def increment(cls):
        cls.count += 1

    @staticmethod
    def is_valid(value):
        return isinstance(value, int) and value >= 0
```

## 4. 文件操作

Python 使用 `open()` 内置函数进行文件操作，推荐使用 `with` 语句自动管理资源。

### 4.1 读取文件

```python
# 读取整个文件
with open("data.txt", "r", encoding="utf-8") as f:
    content = f.read()

# 逐行读取
with open("data.txt", "r", encoding="utf-8") as f:
    for line in f:
        print(line.strip())
```

### 4.2 写入文件

```python
# 写入文本
with open("output.txt", "w", encoding="utf-8") as f:
    f.write("Hello, World!\n")

# 追加文本
with open("log.txt", "a", encoding="utf-8") as f:
    f.write("New log entry\n")
```

### 4.3 JSON 处理

```python
import json

# 写入 JSON
data = {"name": "Alice", "scores": [95, 87, 92]}
with open("data.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

# 读取 JSON
with open("data.json", "r", encoding="utf-8") as f:
    loaded = json.load(f)
```

## 5. 异常处理

Python 使用 `try-except` 语句处理异常，支持多个 except 子句和 finally 子句。

### 5.1 基本语法

```python
try:
    result = 10 / 0
except ZeroDivisionError:
    print("不能除以零")
except (TypeError, ValueError) as e:
    print(f"类型或值错误: {e}")
else:
    print(f"结果是: {result}")
finally:
    print("无论如何都会执行")
```

### 5.2 自定义异常

```python
class InvalidAgeError(Exception):
    def __init__(self, age, message="年龄必须在 0-150 之间"):
        self.age = age
        self.message = message
        super().__init__(self.message)

def set_age(age):
    if not 0 <= age <= 150:
        raise InvalidAgeError(age)
    return age
```

## 6. 常用标准库

Python 标准库非常丰富，以下是常用的模块：

| 模块 | 用途 |
|------|------|
| `os` | 操作系统接口（文件、目录操作） |
| `sys` | 系统相关参数和函数 |
| `datetime` | 日期和时间处理 |
| `json` | JSON 编解码 |
| `re` | 正则表达式 |
| `collections` | 高性能容器数据类型 |
| `itertools` | 迭代器工具 |
| `functools` | 高阶函数工具 |
| `pathlib` | 面向对象的路径操作 |
| `logging` | 日志记录 |
| `argparse` | 命令行参数解析 |
| `unittest` | 单元测试框架 |

## 7. 虚拟环境

Python 虚拟环境用于隔离项目依赖，避免不同项目之间的包冲突。

### 使用 venv

```bash
# 创建虚拟环境
python -m venv myenv

# 激活（Windows）
myenv\Scripts\activate

# 激活（Linux/Mac）
source myenv/bin/activate

# 安装依赖
pip install fastapi uvicorn

# 导出依赖
pip freeze > requirements.txt

# 退出虚拟环境
deactivate
```

### 使用 pip

```bash
pip install package_name       # 安装包
pip install package==1.0.0     # 安装指定版本
pip uninstall package_name     # 卸载包
pip list                       # 查看已安装包
pip show package_name          # 查看包详情
```
