'''
// TS 代码
interface MyJobInfo {
  title: string;
  company: string;
  location: string;
  people: number
}

let name: string = "dxw"; // 字符串
let age: number = 18; // 数字
let isStudent: boolean = true; // 布尔值
let NULL: null = null; // 空值
let UNDEFINED: undefined = undefined; // 未定义
let hobbies: string[] = ["coding", "reading"]; // 字符串数组

let myJobInfo: MyJobInfo = {
  title: "Software Engineer",
  company: "Tech Co.",
  location: "Remote",
  people: 14
}; // 对象
'''
name: str = "dxw"
age: int = 18
isStudent: bool = True  # 第一个字母是大写
NULL: None  # 只有 None
UNDEFINED: None
hobbies: list[str] = ["coding", "reading"]
myJobInfo: dict[str, str | int] = {
  "title": "Software Engineer",
  "company": "Tech Co.",
  "location": "Remote",
  "people": 14
}